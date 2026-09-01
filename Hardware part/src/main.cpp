#include <Arduino.h>
#include <esp_task_wdt.h>
#include <esp_system.h>
#include "config.h"
#include "hal/io_controller.h"
#include "hal/rtc_service.h"
#include "hal/rfid_reader.h"
#include "storage/event_queue.h"
#include "domain/acl_engine.h"
#include "network/network_manager.h"

TaskHandle_t NetworkTask = nullptr;

// ============================================================
// 12. SETUP & LOOP (Core 1)
// ============================================================
void setup() {
    Serial.begin(115200);
    delay(1000);

    Serial.printf("Reset reason: %d\n", esp_reset_reason());
    
    esp_task_wdt_init(10, true);
    esp_task_wdt_add(NULL);

    IOController::init();
    EventQueue::init();
    ACLEngine::init();
    RTCService::init();
    RFIDReader::init();

    xTaskCreatePinnedToCore(NetworkManager::taskLoop, "NetworkTask", 12000, nullptr, 1, &NetworkTask, 0);
    Serial.println("Setup complete.");
}

void loop() {
    esp_task_wdt_reset();
    IOController::update();
    IOController::handleExitButton();
    RFIDReader::update();
    vTaskDelay(1 / portTICK_PERIOD_MS);
}