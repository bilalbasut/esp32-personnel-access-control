#include "io_controller.h"
#include "config.h"
#include "types.h"
#include "rtc_service.h"
#include "../storage/event_queue.h"

static bool isRelayActive = false;
static bool isSuccessBeepActive = false;
static bool isDenySequenceActive = false;
static unsigned long relayStartTime = 0;
static unsigned long successBeepStartTime = 0;
static unsigned long lastDenyStepTime = 0;
static uint8_t denyBeepCount = 0;
static bool denyLedState = false;

static bool lastExitButtonState = HIGH;
static bool stableExitButtonState = HIGH;
static unsigned long lastExitDebounceTime = 0;

void IOController::init() {
    pinMode(RELAY_PIN, OUTPUT);
    pinMode(GREEN_LED_PIN, OUTPUT);
    pinMode(BUZZER_PIN, OUTPUT);
    pinMode(RED_LED_PIN, OUTPUT);
    pinMode(EXIT_BUTTON_PIN, INPUT);

    digitalWrite(RELAY_PIN, LOW);
    digitalWrite(GREEN_LED_PIN, LOW);
    digitalWrite(BUZZER_PIN, LOW);
    digitalWrite(RED_LED_PIN, LOW);
}

bool IOController::isRelayRunning() {
    return isRelayActive;
}

void IOController::grantAccess() {
    isDenySequenceActive = false;
    digitalWrite(RED_LED_PIN, LOW);
    isRelayActive = true;
    relayStartTime = millis();
    digitalWrite(RELAY_PIN, HIGH);
    digitalWrite(GREEN_LED_PIN, HIGH);
    isSuccessBeepActive = true;
    successBeepStartTime = millis();
    digitalWrite(BUZZER_PIN, HIGH);
}

void IOController::denyAccess() {
    if (isRelayActive) return;
    isDenySequenceActive = true;
    denyBeepCount = 0;
    denyLedState = true;
    lastDenyStepTime = millis();
    digitalWrite(RED_LED_PIN, HIGH);
    digitalWrite(BUZZER_PIN, HIGH);
}

// delay() değil millis() tabanlı state machine - aynı loop'taki RFID okuma/watchdog'u kilitlemesin diye.
void IOController::update() {
    const unsigned long now = millis();
    if (isRelayActive && now - relayStartTime >= RELAY_DURATION_MS) {
        isRelayActive = false;
        digitalWrite(RELAY_PIN, LOW);
        digitalWrite(GREEN_LED_PIN, LOW);
    }
    if (isSuccessBeepActive && now - successBeepStartTime >= SUCCESS_BEEP_MS) {
        isSuccessBeepActive = false;
        digitalWrite(BUZZER_PIN, LOW);
    }
    if (isDenySequenceActive && now - lastDenyStepTime >= DENY_STEP_MS) {
        lastDenyStepTime = now;
        if (denyLedState) {
            digitalWrite(RED_LED_PIN, LOW);
            digitalWrite(BUZZER_PIN, LOW);
            denyLedState = false;
            denyBeepCount++;
        } else {
            if (denyBeepCount < 3) {
                digitalWrite(RED_LED_PIN, HIGH);
                digitalWrite(BUZZER_PIN, HIGH);
                denyLedState = true;
            } else {
                isDenySequenceActive = false;
            }
        }
    }
}

void IOController::handleExitButton() {
    bool reading = digitalRead(EXIT_BUTTON_PIN);
    if (reading != lastExitButtonState) lastExitDebounceTime = millis();
    if (millis() - lastExitDebounceTime >= EXIT_DEBOUNCE_MS) {
        if (reading != stableExitButtonState) {
            stableExitButtonState = reading;
            if (stableExitButtonState == LOW && !isRelayActive) {
                // Kart yok, bu yüzden all-zero UID + RESULT_MANUAL (bkz. collector.py MAP_RESULT["manual"]).
                static const uint8_t zeroUid[7] = {0};
                DateTime now = RTCService::rtcNowSafe();
                if (EventQueue::logAccess(now, zeroUid, 7, DEVICE_DIR, RESULT_MANUAL)) {
                    grantAccess();
                    Serial.println("EXIT BUTTON -> GRANTED");
                } else {
                    denyAccess();
                    Serial.println("SYSTEM ERROR: Exit button logging failed.");
                }
            }
        }
    }
    lastExitButtonState = reading;
}