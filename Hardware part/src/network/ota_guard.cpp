#include "network/ota_guard.h"

// Bu sınıf, hatalı bir OTA push'unun sahadaki kapı okuyucularını kalıcı
// olarak "tuğlaya" (brick) çevirmesini engelliyor. Kısaca Eğer ESP32 OTA ile
// güncellenirse ve yeni versiyon kısa sürede Mqtt'ye bağlanamazsa
// bir önceki sürüme geri döndürüyor.

const esp_partition_t* OtaGuard::s_running_partition = nullptr;
bool OtaGuard::s_is_pending_verify = false;
bool OtaGuard::s_verified = false;
uint32_t OtaGuard::s_deadline_ms = 0;

void OtaGuard::init(uint32_t timeout_ms) {
    s_running_partition = esp_ota_get_running_partition();
    esp_ota_img_states_t ota_state;

    if (esp_ota_get_state_partition(s_running_partition, &ota_state) == ESP_OK) {
        if (ota_state == ESP_OTA_IMG_PENDING_VERIFY) {
            s_is_pending_verify = true;
            s_deadline_ms = millis() + timeout_ms;
            Serial.printf("[OTA-GUARD] Image in slot '%s' pending validation. Rollback timer set to %u ms\n",
                          s_running_partition->label, timeout_ms);
        } else {
            Serial.printf("[OTA-GUARD] Booted stable slot '%s'.\n", s_running_partition->label);
        }
    }
}

void OtaGuard::loop() {
    if (!s_is_pending_verify || s_verified) return;

    if (millis() > s_deadline_ms) {
        rollback("Watchdog expired without central MQTT handshake");
    }
}

void OtaGuard::confirmHealth() {
    if (!s_is_pending_verify || s_verified) return;

    esp_err_t err = esp_ota_mark_app_valid_cancel_rollback();
    if (err == ESP_OK) {
        s_verified = true;
        Serial.printf("[OTA-GUARD] Health confirmed for slot '%s'. Rollback canceled.\n",
                      s_running_partition->label);
    } else {
        Serial.printf("[OTA-GUARD] Failed to cancel rollback. Error: 0x%X\n", err);
    }
}

void OtaGuard::rollback(const char* reason) {
    Serial.printf("[OTA-GUARD] CRITICAL: Invalidating slot '%s' -> %s\n",
                  s_running_partition ? s_running_partition->label : "unknown", reason);
    delay(1000);
    esp_ota_mark_app_invalid_rollback_and_reboot();
}

bool OtaGuard::isPending() {
    return s_is_pending_verify;
}