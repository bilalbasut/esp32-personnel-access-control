#pragma once
#include <RTClib.h>
#include "types.h"

class RTCService {
public:
    static void init();
    static DateTime rtcNowSafe();
    static void rtcAdjustSafe(const DateTime& dt);
    
    static volatile uint8_t currentTimeSource;
    static unsigned long lastNtpSync;
    static SemaphoreHandle_t rtcMutex;
};