// =============================================================================
// RecovR MUX Channel Verification Sketch -- Seeed Studio XIAO-ESP32 C3
// =============================================================================
//
// READ-ONLY diagnostic tool. Does NOT connect to BLE, does NOT run any game
// logic, and does NOT modify the production firmware (controller_esp32c3.ino)
// in any way -- it's a separate, temporary sketch you flash, use, then
// re-flash the real firmware over.
//
// Purpose: find out which physical MUX channel (C0-C15) each of the five
// Flex Sensors is actually wired to, before the production firmware is
// updated to read five independent sensors instead of one.
//
// Wiring assumed identical to the production firmware (requirements.md):
//   CD74HC4067 MUX   SIG -> D0 (GPIO2)   S0 -> D1   S1 -> D2   S2 -> D3   S3 -> D6
//
// HOW TO USE
// ----------
// 1. Flash this sketch (Arduino IDE, same board settings as the production
//    firmware: board = XIAO_ESP32C3, upload speed 921600).
// 2. Open Serial Monitor at 115200 baud.
// 3. With your hand fully relaxed, let it print a few lines -- these are your
//    baseline / "nothing happening" readings for all 16 channels. Known-used
//    channels today: C0 = Flex Sensor, C5 = FSR402, C10 = push button.
// 4. Flex ONLY your THUMB, hold ~2 seconds, release. Watch the printed line:
//    exactly one channel's number will rise and fall in step with your
//    thumb. Write down "Thumb = C<n>".
// 5. Repeat one finger at a time for Index, Middle, Ring, Pinky.
// 6. Also flex check: press the FSR -- its channel should move (expected C5).
//    Press the push button -- its channel should jump high (expected C10).
//    If either of those is NOT where expected, say so too -- something
//    shifted and the production firmware's channel map needs updating for
//    those as well, not just the new flex sensors.
// 7. Report back the five Thumb..Pinky channel numbers (and the FSR/button
//    numbers if they weren't C5/C10) so they can be set in the production
//    firmware's hardware configuration block.
// =============================================================================

#define MUX_SIG  2    // D0 -- ADC input from MUX SIG pin
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
    return (uint16_t)analogRead(MUX_SIG);   // 12-bit: 0-4095
}

void setup() {
    Serial.begin(115200);
    delay(500);
    Serial.println();
    Serial.println("[MUX TEST] RecovR MUX channel verification");
    Serial.println("[MUX TEST] Reading all 16 channels every 500ms.");
    Serial.println("[MUX TEST] Flex ONE finger at a time and watch which");
    Serial.println("[MUX TEST] channel's value rises and falls with it.");
    Serial.println("[MUX TEST] Known-used today: C0=flex, C5=FSR, C10=button.");
    Serial.println();

    pinMode(MUX_S0, OUTPUT);
    pinMode(MUX_S1, OUTPUT);
    pinMode(MUX_S2, OUTPUT);
    pinMode(MUX_S3, OUTPUT);
    analogReadResolution(12);
}

void loop() {
    for (uint8_t ch = 0; ch < 16; ch++) {
        uint16_t v = readMuxChannel(ch);
        Serial.printf("C%-2u:%4u  ", ch, v);
        if (ch == 7) Serial.print(" | ");   // split into two rows of 8 for readability
    }
    Serial.println();
    delay(500);
}
