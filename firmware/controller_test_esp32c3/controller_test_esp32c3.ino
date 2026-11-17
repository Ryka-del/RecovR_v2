// =============================================================================
// RecovR Wireless Controller -- HARDWARE TEST ONLY (no BLE)
// Seeed Studio XIAO-ESP32 C3
// =============================================================================
//
// Purpose: verify the repaired controller hardware (MUX + FSR402 + 5-finger
// flex glove + MPU6050) reads sane values BEFORE testing full BLE pairing
// with the RecovR app. Just upload this, open Serial Monitor at 115200 baud,
// and watch the numbers move as you squeeze/bend/tilt things.
//
// Same pins as the main controller firmware (recovr_controller.ino):
//   CD74HC4067 MUX
//     SIG -> D0  (GPIO2, ADC)
//     S0  -> D1  (GPIO3)
//     S1  -> D2  (GPIO4)
//     S2  -> D3  (GPIO5)
//     S3  -> D6  (GPIO21)
//     EN  -> GND (always enabled)
//   FSR402      -> MUX channel C5
//   5-finger flex glove -> MUX channels C0-C4 (Thumb, Index, Middle, Ring, Pinky)
//   MPU6050     -> I2C  SDA=D4(GPIO6)  SCL=D5(GPIO7)
//
// What to check once it's running:
//   - FSR (C5): resting ~0-200, rises sharply (toward 4095) when squeezed.
//   - Each flex channel (C0-C4): resting value steady (not flickering wildly),
//     changes clearly when that specific finger bends. A channel that reads
//     0 or 4095 and never moves usually means a bad connection on that wire.
//   - MPU6050: should print "OK" at startup. ax/ay should sit near 0 when
//     flat and swing by roughly +-16384 (that's 1g) as you tilt the board.
// =============================================================================

#include <Wire.h>
#include <Adafruit_MPU6050.h>
#include <Adafruit_Sensor.h>

// -- Pin definitions (identical to recovr_controller.ino) -------------------
#define MUX_SIG  2    // D0  ADC input from MUX SIG pin
#define MUX_S0   3    // D1
#define MUX_S1   4    // D2
#define MUX_S2   5    // D3
#define MUX_S3   21   // D6

// -- MUX channels --------------------------------------------------------
#define CH_FLEX_THUMB   0   // C0
#define CH_FLEX_INDEX   1   // C1
#define CH_FLEX_MIDDLE  2   // C2
#define CH_FLEX_RING    3   // C3
#define CH_FLEX_PINKY   4   // C4
#define CH_FSR          5   // C5  FSR402

Adafruit_MPU6050 mpu;
bool mpuOK = false;

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

void setup() {
    Serial.begin(115200);
    delay(500);
    Serial.println();
    Serial.println("[RecovR] HARDWARE TEST starting (no BLE)...");

    pinMode(MUX_S0, OUTPUT);
    pinMode(MUX_S1, OUTPUT);
    pinMode(MUX_S2, OUTPUT);
    pinMode(MUX_S3, OUTPUT);
    analogReadResolution(12);   // 12-bit ADC

    Wire.begin(6, 7);   // SDA=GPIO6 (D4), SCL=GPIO7 (D5)
    mpuOK = mpu.begin();
    if (mpuOK) {
        mpu.setAccelerometerRange(MPU6050_RANGE_2_G);
        mpu.setGyroRange(MPU6050_RANGE_250_DEG);
        mpu.setFilterBandwidth(MPU6050_BAND_44_HZ);
        Serial.println("[MPU6050] OK");
    } else {
        Serial.println("[MPU6050] NOT FOUND -- check SDA=D4 / SCL=D5 wiring.");
        Serial.println("[MPU6050] Continuing without tilt; MUX readings still work.");
    }

    Serial.println("[RecovR] Reading sensors every 200ms. Open Serial Monitor @ 115200 baud.");
    Serial.println();
}

void loop() {
    uint16_t fsr_raw    = readMuxChannel(CH_FSR);
    uint16_t thumb_raw  = readMuxChannel(CH_FLEX_THUMB);
    uint16_t index_raw  = readMuxChannel(CH_FLEX_INDEX);
    uint16_t middle_raw = readMuxChannel(CH_FLEX_MIDDLE);
    uint16_t ring_raw   = readMuxChannel(CH_FLEX_RING);
    uint16_t pinky_raw  = readMuxChannel(CH_FLEX_PINKY);

    int16_t accel_x = 0, accel_y = 0, accel_z = 0;
    if (mpuOK) {
        sensors_event_t a, g, temp;
        mpu.getEvent(&a, &g, &temp);
        const float SCALE = 16384.0f / 9.80665f;
        accel_x = (int16_t)(a.acceleration.x * SCALE);
        accel_y = (int16_t)(a.acceleration.y * SCALE);
        accel_z = (int16_t)(a.acceleration.z * SCALE);
    }

    Serial.println("----------------------------------------");
    Serial.printf("FSR402 (grip, C5)   : %4u\n", fsr_raw);
    Serial.printf("Flex Thumb  (C0)     : %4u\n", thumb_raw);
    Serial.printf("Flex Index  (C1)     : %4u\n", index_raw);
    Serial.printf("Flex Middle (C2)     : %4u\n", middle_raw);
    Serial.printf("Flex Ring   (C3)     : %4u\n", ring_raw);
    Serial.printf("Flex Pinky  (C4)     : %4u\n", pinky_raw);
    if (mpuOK) {
        Serial.printf("MPU6050 accel x/y/z  : %6d %6d %6d\n", accel_x, accel_y, accel_z);
    } else {
        Serial.println("MPU6050              : NOT FOUND");
    }

    delay(200);   // 5 Hz -- plenty fast to watch by eye, easy to read
}
