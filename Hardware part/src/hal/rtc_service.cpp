#include "rtc_service.h"
#include <Wire.h>
#include "config.h"

static RTC_PCF8563 rtc;
static DateTime cachedRtcTime(2026, 1, 1, 0, 0, 0);
volatile uint8_t RTCService::currentTimeSource = TSRC_RTC;
unsigned long RTCService::lastNtpSync = 0;
SemaphoreHandle_t RTCService::rtcMutex = NULL;

static uint32_t lastValidEpoch = 1735689600UL; // Base fallback: 2025-01-01
static unsigned long lastValidMillis = 0;

void RTCService::init() {
    rtcMutex = xSemaphoreCreateMutex();
    Wire.begin(I2C_SDA_PIN, I2C_SCL_PIN);
    if (!rtc.begin()) { 
        Serial.println("ERROR: PCF8563 missing."); 
        currentTimeSource = TSRC_INVALID; 
        return; 
    }
    if (rtc.lostPower()) {
        rtcAdjustSafe(DateTime(F(__DATE__), F(__TIME__)));
        currentTimeSource = TSRC_INVALID;
    } else {
        currentTimeSource = TSRC_RTC;
    }
}

DateTime RTCService::rtcNowSafe() {
    unsigned long nowMs = millis();
    DateTime raw;
    bool readSuccess = false;

    if (xSemaphoreTake(rtcMutex, pdMS_TO_TICKS(50)) == pdTRUE) {
        raw = rtc.now();
        xSemaphoreGive(rtcMutex);
        readSuccess = true;
    }

    uint32_t rawEpoch = raw.unixtime();

    // 1. Hard Range Check (Must be between 2025 and 2035)
    bool inRange = (rawEpoch >= 1735689600UL && rawEpoch <= 2051222400UL);

    // 2. Glitch & Spike Filter: RTC cannot advance faster than real elapsed millis()
    bool physicallyPlausible = true;
    if (lastValidMillis > 0 && inRange) {
        unsigned long elapsedSec = (nowMs - lastValidMillis) / 1000;
        // If RTC jumped forward by more than 5 minutes above expected elapsed time without NTP
        if (rawEpoch > (lastValidEpoch + elapsedSec + 300)) {
            physicallyPlausible = false;
        }
    }

    if (readSuccess && inRange && physicallyPlausible) {
        lastValidEpoch = rawEpoch;
        lastValidMillis = nowMs;
        return raw;
    }

    // --- RECOVERY VIA DEAD RECKONING ---
    // If RTC returned 2041, 1970, or corrupted I2C noise, calculate time using millis()
    Serial.printf("WARNING: RTC corruption detected (%lu). Using dead reckoning.\n", rawEpoch);
    currentTimeSource = TSRC_INVALID; // Mark audit flag per FR-10

    if (lastValidMillis == 0) lastValidMillis = nowMs;
    uint32_t estimatedEpoch = lastValidEpoch + ((nowMs - lastValidMillis) / 1000);
    return DateTime(estimatedEpoch);
}

void RTCService::rtcAdjustSafe(const DateTime& dt) {
    if (xSemaphoreTake(rtcMutex, pdMS_TO_TICKS(50)) == pdTRUE) {
        rtc.adjust(dt);
        cachedRtcTime = dt;
        xSemaphoreGive(rtcMutex);
    } else {
        Serial.println("WARNING: rtcMutex contended, skipping RTC adjustment.");
    }
}