// =============================================================================
// RecovR Wireless Controller -- FULL 16-CHANNEL MUX SCAN (no BLE)
// Seeed Studio XIAO-ESP32 C3
// =============================================================================
//
// Purpose: the normal hardware test only reads the 6 channels the firmware
// expects to use (C0-C4 flex, C5 FSR). If FSR (C5) moves correctly but NONE
// of C0-C4 move when bending a finger, that proves the MUX/ADC path itself
// is fine -- the flex sensors are just not actually landing on channels
// 0-4. This sketch prints ALL 16 channels (C0-C15) every cycle so you can
// bend ONE finger at a time and see which channel number actually reacts,
// wherever it really is.
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
// How to use:
//   1. Upload, open Serial Monitor @ 115200 baud.
//   2. Leave everything resting -- note the 16 baseline numbers.
//   3. Bend ONE finger (say, Thumb) and hold it bent. Watch which channel
//      number's value jumps. That is the REAL channel that finger is wired
//      to -- it may not be C0.
//   4. Repeat one finger at a time for Index/Middle/Ring/Pinky.
//   5. Report which physical finger maps to which channel number so the
//      CH_FLEX_* defines in the real firmware can be updated to match.
// =============================================================================

#define MUX_SIG  2    // D0  ADC input from MUX SIG pin
#define MUX_S0   3    // D1
#define MUX_S1   4    // D2
#define MUX_S2   5    // D3
#define MUX_S3   21   // D6

void selectMuxChannel(uint8_t ch) {
    digitalWrite(MUX_S0, (ch >> 0) & 0x01);
    digitalWrite(MUX_S1, (ch >> 1) & 0x01);
    digitalWrite(MUX_S2, (ch >> 2) & 0x01);
    digitalWrite(MUX_S3, (ch >> 3) & 0x01);
    delayMicroseconds(10);
}

uint16_t readMuxChannel(uint8_t ch) {
    selectMuxChannel(ch);
    return (uint16_t)analogRead(MUX_SIG);
}

void setup() {
    Serial.begin(115200);
    delay(500);
    Serial.println();
    Serial.println("[RecovR] FULL 16-CHANNEL MUX SCAN starting...");

    pinMode(MUX_S0, OUTPUT);
    pinMode(MUX_S1, OUTPUT);
    pinMode(MUX_S2, OUTPUT);
    pinMode(MUX_S3, OUTPUT);
    analogReadResolution(12);

    Serial.println("[RecovR] Bend ONE finger at a time and watch which C# moves.");
    Serial.println();
}

void loop() {
    uint16_t readings[16];
    for (uint8_t ch = 0; ch < 16; ch++) {
        readings[ch] = readMuxChannel(ch);
    }

    Serial.println("----------------------------------------");
    for (uint8_t ch = 0; ch < 16; ch++) {
        Serial.printf("C%-2u: %4u   ", ch, readings[ch]);
        if (ch % 4 == 3) Serial.println();
    }
    Serial.println();

    delay(300);
}
