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
        // ÖNEMLİ - saha kaynaklı "olaylar 20XX gibi yanlış bir yılda görünüyor"
        // şikayetlerinin en olası kaynağı burası: lostPower() true dönüyorsa
        // (RTC'nin yedek pili bitmiş/hiç takılmamış, ya da cihaz ilk kez
        // ayağa kalkıyor) RTC, GERÇEK zaman yerine bu firmware'in DERLENDİĞİ
        // ANA (__DATE__/__TIME__, derleme makinesinin o anki saat/tarihi)
        // set ediliyor. Derleme makinesinin saati yanlışsa (örn. yanlış
        // ayarlanmış bir sistem saati) RTC de o yanlış tarihe sabitlenir -
        // ve pil gerçekten ölüyse bu, HER güç kesintisi/reset'te (bir OTA
        // reboot'u dahil) tekrar tekrar olur. currentTimeSource = TSRC_INVALID
        // burada bilerek set ediliyor ki bu tahmini zaman event'lerde
        // "şüpheli" olarak işaretlensin ve network_manager.cpp'deki NTP
        // mantığı bunu hızlıca (15sn içinde) düzeltmeye çalışsın - asıl kalıcı
        // düzeltme RTC modülünün pilini kontrol etmek/değiştirmek.
        rtcAdjustSafe(DateTime(F(__DATE__), F(__TIME__)));
        currentTimeSource = TSRC_INVALID;
    } else {
        currentTimeSource = TSRC_RTC;
    }
}

// PCF8563 I2C üzerinden zaman zaman saçma değerler dönebiliyor (I2C
// gürültüsü, çip arızası vb.) - bu fonksiyon RTC'ye körü körüne güvenmek
// yerine iki kontrolden geçiriyor: (1) makul bir yıl aralığında mı,
// (2) son okunan geçerli zamana göre "fiziksel olarak mümkün" mü (RTC,
// geçen gerçek süreden çok daha fazla ileri sıçramış olamaz). İkisi de
// geçmezse RTC'yi yok sayıp millis() farkına göre tahmini zaman üretiyoruz
// ("dead reckoning") ve tsrc=INVALID işaretliyoruz ki backend/rapor
// tarafında bu event'in saati şüpheli olduğu bilinsin.
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