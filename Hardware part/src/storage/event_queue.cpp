#include "event_queue.h"
#include <LittleFS.h>
#include <Preferences.h>
#include <esp_task_wdt.h>
#include "config.h"
#include "../hal/rtc_service.h"
#include "../network/network_manager.h"
#include "../domain/acl_engine.h"

static Preferences preferences;
static uint32_t readPointer = 0, writePointer = 0, globalSequence = 0;
static uint32_t queueCount = 0;
static uint32_t queueOverflowCount = 0;
static uint32_t eventsSinceCheckpoint = 0, acksSinceCheckpoint = 0;
static portMUX_TYPE queueMux = portMUX_INITIALIZER_UNLOCKED;

static uint32_t queueDistance(uint32_t r, uint32_t w) { return (w >= r) ? w - r : (MAX_EVENTS - r + w); }

File openEventFile(const char* mode) { return LittleFS.open(EVENT_FILE, mode); }

bool writeEventRecord(const AccessRecord& record, uint32_t index) {
    File file = openEventFile("r+");
    if (!file) file = openEventFile("w+");
    if (!file) { Serial.println("ERROR: Cannot open events.bin"); return false; }
    
    if (!file.seek(index * RECORD_SIZE, SeekSet)) { file.close(); return false; }
    size_t written = file.write(reinterpret_cast<const uint8_t*>(&record), sizeof(record));
    file.flush(); file.close();
    return written == sizeof(record);
}

bool EventQueue::readEventRecord(uint32_t index, AccessRecord& record) {
    File file = openEventFile(FILE_READ);
    if (!file) return false;
    uint32_t offset = index * RECORD_SIZE;
    if (file.size() < offset + RECORD_SIZE || !file.seek(offset, SeekSet)) { file.close(); return false; }
    size_t readBytes = file.read(reinterpret_cast<uint8_t*>(&record), sizeof(record));
    file.close();
    return readBytes == sizeof(record);
}

static bool evictOldestIfFull() {
    bool wasFull = false;
    portENTER_CRITICAL(&queueMux);
    if (queueCount >= MAX_EVENTS) {
        readPointer = (readPointer + 1) % MAX_EVENTS;
        wasFull = true;
    }
    portEXIT_CRITICAL(&queueMux);
    return wasFull;
}

static void rebuildQueueState() {
    uint32_t newestSeq = 0;
    int newestIndex = -1;
    uint32_t validCount = 0;

    File file = openEventFile(FILE_READ);
    if (!file) {
        readPointer = 0; writePointer = 0; queueCount = 0;
        return;
    }

    AccessRecord record;
    uint32_t i = 0;
    while (file.read(reinterpret_cast<uint8_t*>(&record), sizeof(record)) == sizeof(record)) {
        if (isRecordValid(record)) {
            validCount++;
            if (record.seq > newestSeq) { newestSeq = record.seq; newestIndex = static_cast<int>(i); }
        }
        i++;
        if ((i & 0x3FF) == 0) esp_task_wdt_reset();
    }
    file.close();

    if (newestIndex < 0) {
        readPointer = 0; writePointer = 0; queueCount = 0; return;
    }

    writePointer = (static_cast<uint32_t>(newestIndex) + 1) % MAX_EVENTS;
    globalSequence = max(globalSequence, newestSeq);
    if (readPointer >= MAX_EVENTS) readPointer = 0;

    portENTER_CRITICAL(&queueMux);
    if (readPointer == writePointer && queueCount > 0) {
        queueCount = min(queueCount, (uint32_t)MAX_EVENTS);
    } else {
        queueCount = queueDistance(readPointer, writePointer);
    }
    if (queueCount > MAX_EVENTS) queueCount = validCount;
    uint32_t safeQueueCount = queueCount;
    portEXIT_CRITICAL(&queueMux);

    Serial.printf("Queue rebuilt. read=%d write=%d count=%d\n", readPointer, writePointer, safeQueueCount);
}

void EventQueue::init() {
    if (!LittleFS.begin(false)) { 
        Serial.println("ERROR: LittleFS mount failed. Automatic formatting suppressed for safety."); 
        return; 
    }
    
    if (!LittleFS.exists("/database.bin") && LittleFS.exists("/database.bak")) {
        LittleFS.rename("/database.bak", "/database.bin");
        Serial.println("RECOVERY: Restored /database.bin from .bak file.");
    }

    if (!LittleFS.exists("/database.bin")) {
        File file = LittleFS.open("/database.bin", FILE_WRITE);
        if (file) file.close(); 
    }
    if (!LittleFS.exists(EVENT_FILE)) { 
        File file = LittleFS.open(EVENT_FILE, FILE_WRITE); 
        if (file) file.close(); 
    }

    preferences.begin("access_system", false);
    readPointer = preferences.getUInt("readPtr", 0);
    writePointer = preferences.getUInt("writePtr", 0);
    queueCount = preferences.getUInt("qCount", 0);
    globalSequence = preferences.getUInt("seq", 0);

    if (readPointer >= MAX_EVENTS) readPointer = 0;
    if (writePointer >= MAX_EVENTS) writePointer = 0;

    rebuildQueueState();
}

void EventQueue::saveCheckpoint(bool force) {
    if (!force && eventsSinceCheckpoint < CHECKPOINT_EVENT_INTERVAL && acksSinceCheckpoint < CHECKPOINT_ACK_INTERVAL) return;
    preferences.putUInt("readPtr", readPointer);
    preferences.putUInt("writePtr", writePointer);
    preferences.putUInt("qCount", queueCount);
    preferences.putUInt("seq", globalSequence);
    preferences.putUInt("aclVer", ACLEngine::getCurrentVersion());
    eventsSinceCheckpoint = 0; acksSinceCheckpoint = 0;
}

bool EventQueue::queueIsEmpty() {
    portENTER_CRITICAL(&queueMux);
    bool empty = (queueCount == 0);
    portEXIT_CRITICAL(&queueMux);
    return empty;
}

void EventQueue::advanceReadPointer() {
    portENTER_CRITICAL(&queueMux);
    readPointer = (readPointer + 1) % MAX_EVENTS;
    if (queueCount > 0) queueCount--;
    portEXIT_CRITICAL(&queueMux);
    acksSinceCheckpoint++;
    saveCheckpoint(false);
}

void EventQueue::incrementAcks() {
    acksSinceCheckpoint++;
}

uint32_t EventQueue::getReadPointer() { return readPointer; }
uint32_t EventQueue::getQueueCount() {
    portENTER_CRITICAL(&queueMux);
    uint32_t c = queueCount;
    portEXIT_CRITICAL(&queueMux);
    return c;
}
uint32_t EventQueue::getQueueOverflowCount() { return queueOverflowCount; }

bool EventQueue::logAccess(const DateTime& now, const uint8_t* uidBytes, uint8_t uidLen, uint8_t direction, uint8_t resultCode) {
    bool overwroteOldest = evictOldestIfFull();
    if (overwroteOldest) {
        queueOverflowCount++;
        Serial.printf("WARNING: Queue full - oldest event overwritten (total overflow=%u)\n", queueOverflowCount);
    }

    AccessRecord record = {};
    record.seq = ++globalSequence;
    record.ts = now.unixtime();
    record.uidLen = min(uidLen, (uint8_t)7);
    memcpy(record.uid, uidBytes, record.uidLen);
    record.dir = direction;
    record.result = resultCode;
    record.mode = NetworkManager::isMqttConnected() ? 0 : 1;
    record.tsrc = RTCService::currentTimeSource;
    record.floor = FLOOR_NUMBER;
    record.crc16 = calculateRecordCRC(record);

    if (!writeEventRecord(record, writePointer)) {
        globalSequence--;
        Serial.println("ERROR: Event write failed.");
        return false;
    }

    writePointer = (writePointer + 1) % MAX_EVENTS;
    portENTER_CRITICAL(&queueMux);
    if (!overwroteOldest) queueCount++;
    portEXIT_CRITICAL(&queueMux);
    eventsSinceCheckpoint++;
    Serial.printf("EVENT STORED seq=%d\n", record.seq);
    saveCheckpoint(false);
    return true;
}