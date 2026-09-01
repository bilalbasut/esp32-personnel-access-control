#pragma once
#include <Arduino.h>
#include <RTClib.h>
#include <vector>
#include "types.h"

class ACLEngine {
public:
    static void init();
    static void loadAclToRAM();
    static uint8_t evaluateAccess(const uint8_t* scannedUid, uint8_t uidLen, const DateTime& now);
    static void processACLUpdate(std::vector<uint8_t>& pendingBytes);
    static uint32_t getCurrentVersion();
    static void resetVersion();
};