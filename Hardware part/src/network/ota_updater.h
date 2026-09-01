#pragma once
#include <Arduino.h>

class OTAUpdater {
public:
    static bool performOTA(const String& url, const String& expectedMd5, uint32_t expectedSize);
};