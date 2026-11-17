// =============================================================================
// RecovR Wireless Controller -- Seeed Studio XIAO-ESP32 C3
// =============================================================================
//
// Arduino IDE setup:
//   Boards Manager : "esp32" by Espressif Systems
//   Board          : XIAO_ESP32C3
//   Upload speed   : 921600      Serial monitor: 115200
//
// Hardware:
//   CD74HC4067 MUX
//     SIG -> D0  (GPIO2, ADC)
//     S0  -> D1  (GPIO3)
//     S1  -> D2  (GPIO4)
//     S2  -> D3  (GPIO5)
//     S3  -> D6  (GPIO21)
//     EN  -> GND (always enabled)
//   FSR402      -> MUX channel C4
//   MPU6050     -> I2C  SDA=D4(GPIO6)  SCL=D5(GPIO7)
//   No push button is wired -- the "buttons" byte in the BLE packet below
//   is always sent as 0 (kept so the packet layout/size never changes).
//
//   5-finger flex glove -- WIRING:
//     flex1 Thumb  = C5
//     flex2 Index  = C6
//     flex3 Middle = C7
//     flex4 Ring   = C8
//     flex5 Pinky  = C9
//   Used independently by Tile Rush and Whack-a-Mole (state["finger_flex"],
//   5 separate channels). Plant the Garden instead uses only the Thumb
//   channel (C5) as its single legacy "Finger Flexion" reading
//   (state["tilt_y"]) -- same physical sensor, not a second one. Steady Aim
//   and Purrfect Feast use NO flex sensor at all today (per
//   scenes/therapist_dashboard.py's MULTI_SENSOR_CALIBRATION -- Steady Aim is
//   Wrist Rotation only, Purrfect Feast is Grip + Wrist only). If Purrfect
//   Feast is meant to need flex too, that's a game-logic change, not a
//   wiring one -- flag it separately.
//
// BLE Packet (19 bytes, little-endian, 50 Hz) -- must match
// sensors/ble_receiver.py PACKET_FORMAT "<HHHHHHHBhh":
//   [0-1]   uint16  grip_raw        FSR ADC value  (C4)    0-4095
//   [2-3]   uint16  flex_raw        Flex ADC (legacy, C5)  0-4095
//   [4-5]   uint16  flex_thumb_raw  Thumb Flex ADC  (C5)   0-4095
//   [6-7]   uint16  flex_index_raw  Index Flex ADC  (C6)   0-4095
//   [8-9]   uint16  flex_middle_raw Middle Flex ADC (C7)   0-4095
//   [10-11] uint16  flex_ring_raw   Ring Flex ADC   (C8)   0-4095
//   [12-13] uint16  flex_pinky_raw  Pinky Flex ADC  (C9)   0-4095
//   [14]    uint8   buttons         bit0 = push button (1=pressed)
//   [15-16] int16   accel_x         MPU6050 accel X  (16384 LSB/g at +/-2g)
//   [17-18] int16   accel_y         MPU6050 accel Y
//
// Libraries -- install via Arduino Library Manager:
//   Adafruit MPU6050        by Adafruit
//   Adafruit Unified Sensor by Adafruit
//
// BLE uses the built-in ESP32 BLE library (no extra install needed).
//
// ADVERTISING NOTE (important):
//   A BLE advertising packet is only 31 bytes. Flags (3) + a 128-bit service
//   UUID (18) + the name "RecovR-Controller" (19) = 40 bytes -- too big, and
//   the stack silently DROPS the name. The PC then sees a nameless device and
//   never matches it. Fix: enable the scan response, which carries the name in
//   a second 31-byte packet. Do not set setScanResponse(false) here.
// =============================================================================

#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLEUtils.h>
#include <BLE2902.h>
#include <Wire.h>
#include <Adafruit_MPU6050.h>
#include <Adafruit_Sensor.h>

// -- Pin definitions ----------------------------------------------------------
#define MUX_SIG  2    // D0  ADC input from MUX SIG pin
#define MUX_S0   3    // D1
#define MUX_S1   4    // D2
#define MUX_S2   5    // D3
#define MUX_S3   21   // D6

// -- MUX channels -------------------------------------------------------------
#define CH_FSR          4   // C4  FSR402

// 5-finger glove (flex1-flex5 = C5-C9, Thumb through Pinky)
#define CH_FLEX_THUMB   5   // C5  flex1
#define CH_FLEX_INDEX   6   // C6  flex2
#define CH_FLEX_MIDDLE  7   // C7  flex3
#define CH_FLEX_RING    8   // C8  flex4
#define CH_FLEX_PINKY   9   // C9  flex5

// Legacy single-flex reading (Plant the Garden) = same physical Thumb sensor
#define CH_FLEX         CH_FLEX_THUMB   // C5

// -- BLE identity (must match sensors/ble_receiver.py) ------------------------
#define DEVICE_NAME  "RecovR-Controller"
#define SERVICE_UUID "12345678-1234-1234-1234-123456789abc"
#define CHAR_UUID    "12345678-1234-1234-1234-123456789abd"

// -- Send rate ----------------------------------------------------------------
#define SEND_INTERVAL_MS 20   // 50 Hz

// -- Globals ------------------------------------------------------------------
Adafruit_MPU6050   mpu;
BLEServer*         pServer         = nullptr;
BLECharacteristic* pCharacteristic = nullptr;
BLEAdvertising*    pAdvertising    = nullptr;
bool deviceConnected = false;
bool prevConnected   = false;
bool mpuOK           = false;

// -- BLE server callbacks -----------------------------------------------------
class MyServerCallbacks : public BLEServerCallbacks {
    void onConnect(BLEServer* pSvr) {
        deviceConnected = true;
        Serial.println("[BLE] Client connected");
    }
    void onDisconnect(BLEServer* pSvr) {
        deviceConnected = false;
        Serial.println("[BLE] Client disconnected");
    }
};

// -- MUX helpers --------------------------------------------------------------
void selectMuxChannel(uint8_t ch) {
    digitalWrite(MUX_S0, (ch >> 0) & 0x01);
    digitalWrite(MUX_S1, (ch >> 1) & 0x01);
    digitalWrite(MUX_S2, (ch >> 2) & 0x01);
    digitalWrite(MUX_S3, (ch >> 3) & 0x01);
    delayMicroseconds(10);
}

uint16_t readMuxChannel(uint8_t ch) {
    selectMuxChannel(ch);
    return (uint16_t)analogRead(MUX_SIG);   // 12-bit: 0-4095
}

// -- Little-endian packing (uses lowByte/highByte to avoid IDE emoji bug) -----
void packU16(uint8_t* buf, uint16_t val) {
    buf[0] = lowByte(val);
    buf[1] = highByte(val);
}

void packI16(uint8_t* buf, int16_t val) {
    buf[0] = lowByte((uint16_t)val);
    buf[1] = highByte((uint16_t)val);
}

// -- setup() ------------------------------------------------------------------
void setup() {
    Serial.begin(115200);
    delay(500);
    Serial.println();
    Serial.println("[RecovR] Controller starting...");

    // MUX select pins
    pinMode(MUX_S0, OUTPUT);
    pinMode(MUX_S1, OUTPUT);
    pinMode(MUX_S2, OUTPUT);
    pinMode(MUX_S3, OUTPUT);
    analogReadResolution(12);   // 12-bit ADC

    // MPU6050 -- a missing IMU must NOT stop BLE, or grip/flex die with it.
    Wire.begin(6, 7);   // SDA=GPIO6, SCL=GPIO7
    mpuOK = mpu.begin();
    if (mpuOK) {
        mpu.setAccelerometerRange(MPU6050_RANGE_2_G);
        mpu.setGyroRange(MPU6050_RANGE_250_DEG);
        mpu.setFilterBandwidth(MPU6050_BAND_44_HZ);
        Serial.println("[MPU6050] OK");
    } else {
        Serial.println("[MPU6050] NOT FOUND -- check SDA=D4 / SCL=D5 wiring.");
        Serial.println("[MPU6050] Continuing without tilt; grip + flex still work.");
    }

    // BLE
    BLEDevice::init(DEVICE_NAME);
    // Lowest TX power -- genuinely reduces the radio's current draw (unlike
    // disabling the brownout detector, which only hides a voltage dip
    // instead of shrinking it) at the moment advertising starts, which is
    // the exact instant this board has been browning out. Controller sits
    // right next to the Pi/PC in normal use, so the shorter range this
    // trades away doesn't matter here. If this alone isn't enough, the
    // remaining fix is local 3.3V/GND decoupling capacitance on the board
    // itself -- see the chat history for that diagnosis.
    BLEDevice::setPower(ESP_PWR_LVL_N12);
    pServer = BLEDevice::createServer();
    pServer->setCallbacks(new MyServerCallbacks());

    BLEService* pService = pServer->createService(SERVICE_UUID);
    pCharacteristic = pService->createCharacteristic(
        CHAR_UUID,
        BLECharacteristic::PROPERTY_NOTIFY
    );
    pCharacteristic->addDescriptor(new BLE2902());
    pService->start();

    pAdvertising = BLEDevice::getAdvertising();
    pAdvertising->addServiceUUID(SERVICE_UUID);
    // TRUE so the 17-char name fits in the scan-response packet. With false the
    // name + 128-bit UUID overflow the 31-byte advert and the name is dropped,
    // leaving the PC unable to recognise the controller.
    pAdvertising->setScanResponse(true);
    pAdvertising->setMinPreferred(0x06);   // helps iOS/BlueZ connection issues
    pAdvertising->setMaxPreferred(0x12);
    BLEDevice::startAdvertising();

    Serial.print("[BLE] Advertising as '");
    Serial.print(DEVICE_NAME);
    Serial.println("' -- waiting for RecovR to connect.");
}

// -- loop() -------------------------------------------------------------------
void loop() {
    // Restart advertising after a client disconnects
    if (!deviceConnected && prevConnected) {
        delay(200);
        BLEDevice::startAdvertising();
        Serial.println("[BLE] Restarting advertising...");
    }
    prevConnected = deviceConnected;

    // Throttle to SEND_INTERVAL_MS
    static unsigned long lastSend = 0;
    unsigned long now = millis();
    if (now - lastSend < SEND_INTERVAL_MS) return;
    lastSend = now;

    // Read sensors via MUX
    uint16_t grip_raw        = readMuxChannel(CH_FSR);           // C4
    uint16_t flex_thumb_raw  = readMuxChannel(CH_FLEX_THUMB);    // C5  flex1
    uint16_t flex_index_raw  = readMuxChannel(CH_FLEX_INDEX);    // C6  flex2
    uint16_t flex_middle_raw = readMuxChannel(CH_FLEX_MIDDLE);   // C7  flex3
    uint16_t flex_ring_raw   = readMuxChannel(CH_FLEX_RING);     // C8  flex4
    uint16_t flex_pinky_raw  = readMuxChannel(CH_FLEX_PINKY);    // C9  flex5
    uint16_t flex_raw        = flex_thumb_raw;                   // legacy = Thumb (C5)
    uint8_t  buttons  = 0;   // no physical push button wired

    // Read MPU6050 -> raw int16 counts (16384 LSB/g at +/-2g)
    int16_t accel_x = 0, accel_y = 0;
    if (mpuOK) {
        sensors_event_t a, g, temp;
        mpu.getEvent(&a, &g, &temp);
        const float SCALE = 16384.0f / 9.80665f;
        accel_x = (int16_t)(a.acceleration.x * SCALE);
        accel_y = (int16_t)(a.acceleration.y * SCALE);
    }

    // Send BLE notification
    if (deviceConnected) {
        uint8_t packet[19];
        packU16(&packet[0],  grip_raw);
        packU16(&packet[2],  flex_raw);
        packU16(&packet[4],  flex_thumb_raw);
        packU16(&packet[6],  flex_index_raw);
        packU16(&packet[8],  flex_middle_raw);
        packU16(&packet[10], flex_ring_raw);
        packU16(&packet[12], flex_pinky_raw);
        packet[14] = buttons;
        packI16(&packet[15], accel_x);
        packI16(&packet[17], accel_y);
        pCharacteristic->setValue(packet, 19);
        pCharacteristic->notify();
    }

    // Serial debug -- 5 Hz when connected, plus a slow "still advertising"
    // heartbeat when idle so you can tell the board is alive and discoverable.
    static unsigned long lastPrint = 0;
    unsigned long printGap = deviceConnected ? 200 : 2000;
    if (now - lastPrint >= printGap) {
        lastPrint = now;
        Serial.println(deviceConnected ? "[LIVE]" : "[ADV ]");
        Serial.printf("  fsr402         (c4): %u\n", grip_raw);
        Serial.printf("  flex1 thumb    (c5): %u\n", flex_thumb_raw);
        Serial.printf("  flex2 index    (c6): %u\n", flex_index_raw);
        Serial.printf("  flex3 middle   (c7): %u\n", flex_middle_raw);
        Serial.printf("  flex4 ring     (c8): %u\n", flex_ring_raw);
        Serial.printf("  flex5 pinky    (c9): %u\n", flex_pinky_raw);
        if (mpuOK) {
            Serial.printf("  mpu6050: ax=%d ay=%d\n", accel_x, accel_y);
        } else {
            Serial.println("  mpu6050: not found");
        }
    }
}
