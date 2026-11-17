// =============================================================================
// RecovR Wireless Controller -- HARDWARE TEST: 5 FLEX + 5 FSR (no BLE)
// Seeed Studio XIAO-ESP32 C3
// =============================================================================
//
// Purpose: TEST/DIAGNOSTIC ONLY -- verifies a controller wired with 5 flex
// sensors AND 5 FSR sensors (10 total MUX channels). Prints raw readings to
// Serial Monitor only. Does NOT touch the real recovr_controller.ino or
// the BLE packet format -- the Python app (sensors/ble_receiver.py) is
// completely unaffected by this sketch.
//
// Same pins as the main controller firmware:
//   CD74HC4067 MUX
//     SIG -> D0  (GPIO2, ADC)
//     S0  -> D1  (GPIO3)
//     S1  -> D2  (GPIO4)
//     S2  -> D3  (GPIO5)
//     S3  -> D6  (GPIO21)
//     EN  -> GND (always enabled)
//
// Channel map for this test:
//   C0  Flex 1 (e.g. Thumb)
//   C1  Flex 2 (e.g. Index)
//   C2  Flex 3 (e.g. Middle)
//   C3  Flex 4 (e.g. Ring)
//   C4  Flex 5 (e.g. Pinky)
//   C5  FSR 1
//   C6  FSR 2
//   C7  FSR 3
//   C8  FSR 4
//   C9  FSR 5
//
// (This mirrors the same C0-C4 flex assignment the main firmware's header
// comment documents as "VERIFIED WIRING" -- if the scan sketch showed your
// flex sensors actually land on different channel numbers, tell me and
// I'll adjust these defines to match your real wiring instead of guessing.)
//
// How to use:
//   Upload, open Serial Monitor @ 115200 baud. Bend/press one sensor at a
//   time and confirm its own channel number moves while the others stay
//   steady.
// =============================================================================

#define MUX_SIG  2    // D0  ADC input from MUX SIG pin
#define MUX_S0   3    // D1
#define MUX_S1   4    // D2
#define MUX_S2   5    // D3
#define MUX_S3   21   // D6

// -- Flex channels (5) ---------------------------------------------------
#define CH_FLEX_1  0   // C0
#define CH_FLEX_2  1   // C1
#define CH_FLEX_3  2   // C2
#define CH_FLEX_4  3   // C3
#define CH_FLEX_5  4   // C4

// -- FSR channels (5) ------------------------------------------------------
#define CH_FSR_1   5   // C5
#define CH_FSR_2   6   // C6
#define CH_FSR_3   7   // C7
#define CH_FSR_4   8   // C8
#define CH_FSR_5   9   // C9

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
    Serial.println("[RecovR] 5-FLEX + 5-FSR HARDWARE TEST starting (no BLE)...");

    pinMode(MUX_S0, OUTPUT);
    pinMode(MUX_S1, OUTPUT);
    pinMode(MUX_S2, OUTPUT);
    pinMode(MUX_S3, OUTPUT);
    analogReadResolution(12);

    Serial.println("[RecovR] Reading sensors every 200ms. Open Serial Monitor @ 115200 baud.");
    Serial.println();
}

void loop() {
    uint16_t flex1 = readMuxChannel(CH_FLEX_1);
    uint16_t flex2 = readMuxChannel(CH_FLEX_2);
    uint16_t flex3 = readMuxChannel(CH_FLEX_3);
    uint16_t flex4 = readMuxChannel(CH_FLEX_4);
    uint16_t flex5 = readMuxChannel(CH_FLEX_5);

    uint16_t fsr1 = readMuxChannel(CH_FSR_1);
    uint16_t fsr2 = readMuxChannel(CH_FSR_2);
    uint16_t fsr3 = readMuxChannel(CH_FSR_3);
    uint16_t fsr4 = readMuxChannel(CH_FSR_4);
    uint16_t fsr5 = readMuxChannel(CH_FSR_5);

    Serial.println("----------------------------------------");
    Serial.printf("Flex 1 (C0): %4u   Flex 2 (C1): %4u   Flex 3 (C2): %4u\n", flex1, flex2, flex3);
    Serial.printf("Flex 4 (C3): %4u   Flex 5 (C4): %4u\n", flex4, flex5);
    Serial.printf("FSR 1  (C5): %4u   FSR 2  (C6): %4u   FSR 3  (C7): %4u\n", fsr1, fsr2, fsr3);
    Serial.printf("FSR 4  (C8): %4u   FSR 5  (C9): %4u\n", fsr4, fsr5);

    delay(200);
}
