#pragma once
#include <Arduino.h>
#include <RTClib.h>
#include <FS.h>
#include "types.h"

class EventQueue {
public:
    static void init();
    static bool logAccess(const DateTime& now, const uint8_t* uidBytes, uint8_t uidLen, uint8_t direction, uint8_t resultCode);
    static bool readEventRecord(uint32_t index, AccessRecord& record);
    static bool queueIsEmpty();
    static void advanceReadPointer();
    static void saveCheckpoint(bool force = false);
    static void incrementAcks();
    
    static uint32_t getReadPointer();
    static uint32_t getQueueCount();
    static uint32_t getQueueOverflowCount();
};