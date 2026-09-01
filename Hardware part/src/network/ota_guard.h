#pragma once

#include <Arduino.h>
#include "esp_ota_ops.h"

class OtaGuard {
public:
    static void init(uint32_t timeout_ms = 60000);
    static void loop();
    static void confirmHealth();
    static void rollback(const char* reason);
    static bool isPending();

private:
    static const esp_partition_t* s_running_partition;
    static bool s_is_pending_verify;
    static bool s_verified;
    static uint32_t s_deadline_ms;
};