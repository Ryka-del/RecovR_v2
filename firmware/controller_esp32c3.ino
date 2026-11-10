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
//   FSR402      -> MUX channel C5
//   Flex Sensor -> MUX channel C0   (legacy single-flex games: Piano Tiles,
//                                    Plant the Garden, Steady Aim)
//   Push Button -> MUX channel C10  (pull-down resistor to GND)
//   MPU6050     -> I2C  SDA=D4(GPIO6)  SCL=D5(GPIO7)
//
//   Whack-a-Mole (5-finger glove) -- PLACEHOLDER WIRING:
//   the five CH_FLEX_* constants below are NOT yet verified against the real
//   glove. Flash firmware/mux_channel_verify/mux_channel_verify.ino, flex one
//   finger at a time, note which MUX channel (C0-C15) moves for each finger,
//   then replace the five placeholder numbers below with the real ones
//   before relying on per-finger gameplay. Until then they all read the same
//   physical sensor as CH_FLEX, which is harmless (every finger reports the
//   same value, matching this firmware's previous single-sensor behavior)
//   but gives no real finger-to-finger differentiation.
//
// BLE Packet (19 bytes, little-endian, 50 Hz) -- must match
// sensors/ble_receiver.py PACKET_FORMAT "<HHHHHHHBhh":
//   [0-1]   uint16  grip_raw        FSR ADC value         0-4095
//   [2-3]   uint16  flex_raw        Flex ADC (legacy)      0-4095
//   [4-5]   uint16  flex_thumb_raw  Thumb Flex ADC         0-4095
//   [6-7]   uint16  flex_index_raw  Index Flex ADC         0-4095
//   [8-9]   uint16  flex_middle_raw Middle Flex ADC        0-4095
//   [10-11] uint16  flex_ring_raw   Ring Flex ADC          0-4095
//   [12-13] uint16  flex_pinky_raw  Pinky Flex ADC         0-4095
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
#define CH_FLEX    0   // C0  Flex Sensor 2.2 (legacy single-flex games)
#define CH_FSR     5   // C5  FSR402
#define CH_BUTTON  10  // C10 Push button

// Whack-a-Mole 5-finger glove -- PLACEHOLDERS, see the header comment
// above. All five default to CH_FLEX (C0) until verified with
// firmware/mux_channel_verify/mux_channel_verify.ino.
#define CH_FLEX_THUMB   0   // TODO: confirm via mux_channel_verify.ino
#define CH_FLEX_INDEX   0   // TODO: confirm via mux_channel_verify.ino
#define CH_FLEX_MIDDLE  0   // TODO: confirm via mux_channel_verify.ino
#define CH_FLEX_RING    0   // TODO: confirm via mux_channel_verify.ino
#define CH_FLEX_PINKY   0   // TODO: confirm via mux_channel_verify.ino

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
    uint16_t grip_raw        = readMuxChannel(CH_FSR);
    uint16_t flex_raw        = readMuxChannel(CH_FLEX);
    uint16_t flex_thumb_raw  = readMuxChannel(CH_FLEX_THUMB);
    uint16_t flex_index_raw  = readMuxChannel(CH_FLEX_INDEX);
    uint16_t flex_middle_raw = readMuxChannel(CH_FLEX_MIDDLE);
    uint16_t flex_ring_raw   = readMuxChannel(CH_FLEX_RING);
    uint16_t flex_pinky_raw  = readMuxChannel(CH_FLEX_PINKY);
    uint16_t btn_adc  = readMuxChannel(CH_BUTTON);
    uint8_t  buttons  = (btn_adc > 2047) ? 0x01 : 0x00;

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
        Serial.printf("%s grip=%4u flex=%4u T=%4u I=%4u M=%4u R=%4u P=%4u btn=%u ax=%6d ay=%6d\n",
                      deviceConnected ? "[LIVE]" : "[ADV ]",
                      grip_raw, flex_raw, flex_thumb_raw, flex_index_raw,
                      flex_middle_raw, flex_ring_raw, flex_pinky_raw,
                      buttons, accel_x, accel_y);
    }
}
