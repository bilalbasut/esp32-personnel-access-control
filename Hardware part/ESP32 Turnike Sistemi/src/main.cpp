#include <Arduino.h>
#include <Wire.h>
#include <RTClib.h>
#include <FS.h>
#include <LittleFS.h>
#include <SPI.h>
#include <Ethernet.h>
#include <Preferences.h>
#include <ArduinoJson.h>
#include <EthernetUdp.h>
#include <NTPClient.h>
#include <vector>
#include <algorithm>
#include <MQTT.h>
#include <esp_task_wdt.h>
#include <esp_system.h>
#include <Update.h>

#include <MFRC522v2.h>
#include <MFRC522DriverSPI.h>
#include <MFRC522DriverPinSimple.h>

// ============================================================
// 1. CONFIGURATION
// ============================================================
#define FW_VERSION "1.8.1"
#define DEVICE_ID "GATE-K3-01"
#define FLOOR_NUMBER 3
#define DEVICE_DIR DIR_IN // Options: DIR_IN (0) or DIR_OUT (1)

// Hardware Pins
#define RELAY_PIN       32
#define BUZZER_PIN      33
#define GREEN_LED_PIN   25
#define RED_LED_PIN     17
#define EXIT_BUTTON_PIN 35

// W5500 / VSPI
#define W5500_SCK_PIN   18
#define W5500_MISO_PIN  19
#define W5500_MOSI_PIN  23
#define W5500_CS_PIN    5
#define W5500_RST_PIN   4

// MFRC522 / HSPI
#define RFID_SCK_PIN    14
#define RFID_MISO_PIN   27
#define RFID_MOSI_PIN   13
#define RFID_SS_PIN     15

// I2C
#define I2C_SDA_PIN     21
#define I2C_SCL_PIN     22

// Timing
#define RELAY_DURATION_MS       3000UL
#define SUCCESS_BEEP_MS          250UL
#define DENY_STEP_MS             150UL
#define RFID_DEBOUNCE_MS        5000UL
#define EXIT_DEBOUNCE_MS          50UL
#define HEARTBEAT_INTERVAL_MS  30000UL
#define NTP_SYNC_INTERVAL_MS 3600000UL
#define ACK_TIMEOUT_MS          2000UL
#define PUBLISH_RATE_LIMIT_MS     50UL

// OTA Constants
#define OTA_CHUNK_SIZE           512
#define OTA_STALL_TIMEOUT_MS   10000UL
#define OTA_TOTAL_TIMEOUT_MS   60000UL

// Persistent Queue
#define EVENT_FILE "/events.bin"
#define MAX_EVENTS 20000
#define RECORD_SIZE 32
#define CHECKPOINT_EVENT_INTERVAL 64
#define CHECKPOINT_ACK_INTERVAL   16

// ============================================================
// 2. DATA STRUCTURES & ENUMS
// ============================================================
#pragma pack(push, 1)
struct AccessRecord {
    uint32_t seq;
    uint32_t ts;
    uint8_t  uid[7];
    uint8_t  uidLen;
    uint8_t  dir;
    uint8_t  result;
    uint8_t  mode;
    uint8_t  tsrc;
    uint8_t  floor;
    uint8_t  reserved[9];
    uint16_t crc16;
};
#pragma pack(pop)

#pragma pack(push, 1)
struct AclRecord {
    uint8_t  uid[7];
    uint8_t  uidLen;
    uint32_t floor_mask;
    uint32_t valid_to;
    uint16_t win_start_m;
    uint16_t win_end_m;
};
#pragma pack(pop)

#pragma pack(push, 1)
struct AclHeader {
    uint32_t ver;
    uint32_t count;
};
#pragma pack(pop)

static_assert(sizeof(AccessRecord) == RECORD_SIZE, "AccessRecord must be 32 bytes");

enum Direction : uint8_t { DIR_IN = 0, DIR_OUT = 1 };
enum ResultCode : uint8_t { RESULT_GRANTED = 0, RESULT_UNKNOWN = 1, RESULT_EXPIRED = 2, RESULT_SCHEDULE = 3, RESULT_MANUAL = 4 };
enum TimeSource : uint8_t { TSRC_NTP = 0, TSRC_RTC = 1, TSRC_INVALID = 2 };

// ============================================================
// 3. GLOBAL OBJECTS & STATE
// ============================================================
Preferences preferences;
RTC_PCF8563 rtc;
SPIClass hspi(HSPI);

MFRC522DriverPinSimple rfidSS(RFID_SS_PIN);
MFRC522DriverSPI rfidDriver(rfidSS, hspi);
MFRC522 rfid(rfidDriver);

EthernetUDP ntpUDP;
NTPClient timeClient(ntpUDP, "pool.ntp.org", 0, 60000);
EthernetClient ethClient;

MQTTClient mqtt(16384); // 16KB buffer for large ACL messages
TaskHandle_t NetworkTask = nullptr;

// Network Config
byte mac[] = { 0x00, 0x1A, 0x2B, 0x3C, 0x4D, 0x5E };
IPAddress deviceIP(192, 168, 11, 155);
IPAddress dnsIP(8, 8, 8, 8); // Google DNS
IPAddress gatewayIP(192, 168, 10, 1);
IPAddress subnetMask(255, 255, 254, 0);
IPAddress mqttServer(192, 168, 11, 54);
const uint16_t MQTT_PORT = 1883;

// Topics
const char* TOPIC_EVENT     = "pdks/merkez/dev/GATE-K3-01/event";
const char* TOPIC_EVENT_ACK = "pdks/merkez/dev/GATE-K3-01/event/ack";
const char* TOPIC_STATUS    = "pdks/merkez/dev/GATE-K3-01/status";
const char* TOPIC_HEARTBEAT = "pdks/merkez/dev/GATE-K3-01/hb";
const char* TOPIC_ACL       = "pdks/merkez/cfg/acl";
const char* TOPIC_CMD       = "pdks/merkez/dev/GATE-K3-01/cmd";
const char* TOPIC_CMD_RES   = "pdks/merkez/dev/GATE-K3-01/cmd/res";

// RAM State
uint32_t readPointer = 0, writePointer = 0, globalSequence = 0;
uint32_t currentAclVersion = 0, queueCount = 0;
uint32_t queueOverflowCount = 0;
volatile bool rebootPending = false;
unsigned long rebootRequestedAt = 0;
uint32_t eventsSinceCheckpoint = 0, acksSinceCheckpoint = 0;
std::vector<AclRecord> aclList;
uint32_t lastCmdSeq = 0;

// FreeRTOS Synchronization
portMUX_TYPE queueMux = portMUX_INITIALIZER_UNLOCKED;
SemaphoreHandle_t aclMutex = NULL;
SemaphoreHandle_t rtcMutex = NULL;

DateTime cachedRtcTime(2026, 1, 1, 0, 0, 0);
volatile uint8_t currentTimeSource = TSRC_RTC;
unsigned long lastNtpSync = 0;

// Hardware & Debounce State
bool isRelayActive = false, isSuccessBeepActive = false, isDenySequenceActive = false;
unsigned long relayStartTime = 0, successBeepStartTime = 0, lastDenyStepTime = 0;
uint8_t denyBeepCount = 0;
bool denyLedState = false;
bool lastExitButtonState = HIGH, stableExitButtonState = HIGH;
unsigned long lastExitDebounceTime = 0;
uint8_t lastUid[7] = {0};
uint8_t lastUidLen = 0;
unsigned long lastScanTime = 0;

// MQTT Flags
volatile bool ackReceived = false;
volatile uint32_t pendingAckSeq = 0;
volatile bool aclMessageReceived = false;
std::vector<uint8_t> pendingAclBytes;

// ============================================================
// 4. HELPERS (CRC, UID, Formatting, Thread-Safe RTC)
// ============================================================

// Static state for dead reckoning
static uint32_t lastValidEpoch = 1735689600UL; // Base fallback: 2025-01-01
static unsigned long lastValidMillis = 0;

DateTime rtcNowSafe() {
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

void rtcAdjustSafe(const DateTime& dt) {
    if (xSemaphoreTake(rtcMutex, pdMS_TO_TICKS(50)) == pdTRUE) {
        rtc.adjust(dt);
        cachedRtcTime = dt;
        xSemaphoreGive(rtcMutex);
    } else {
        Serial.println("WARNING: rtcMutex contended, skipping RTC adjustment.");
    }
}

uint16_t calculateCRC16(const uint8_t* data, size_t length) {
    uint16_t crc = 0xFFFF;
    for (size_t i = 0; i < length; i++) {
        crc ^= data[i];
        for (uint8_t bit = 0; bit < 8; bit++) crc = (crc & 0x0001) ? (crc >> 1) ^ 0xA001 : (crc >> 1);
    }
    return crc;
}

uint16_t calculateRecordCRC(const AccessRecord& record) {
    return calculateCRC16(reinterpret_cast<const uint8_t*>(&record), sizeof(AccessRecord) - sizeof(record.crc16));
}

bool isRecordValid(const AccessRecord& record) {
    if (record.seq == 0 || record.uidLen > 7) return false;
    return calculateRecordCRC(record) == record.crc16;
}

uint8_t hexNibble(char c) {
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    return 0;
}

bool isValidHex(const char* hex, size_t len) {
    if (len == 0 || len % 2 != 0 || len > 14) return false;
    for (size_t i = 0; i < len; i++) {
        char c = hex[i];
        if (!((c >= '0' && c <= '9') || (c >= 'A' && c <= 'F') || (c >= 'a' && c <= 'f'))) {
            return false;
        }
    }
    return true;
}

void hexToBytes(const char* hex, size_t hexLen, uint8_t* byteArray, uint8_t maxLen) {
    memset(byteArray, 0, maxLen);
    for (size_t i = 0; i + 1 < hexLen && (i / 2) < maxLen; i += 2) {
        byteArray[i / 2] = (hexNibble(hex[i]) << 4) | hexNibble(hex[i + 1]);
    }
}

void bytesToHex(const uint8_t* bytes, uint8_t len, char* out, size_t outSize) {
    static const char hexChars[] = "0123456789ABCDEF";
    size_t pos = 0;
    for (uint8_t i = 0; i < len && pos + 2 < outSize; i++) {
        out[pos++] = hexChars[bytes[i] >> 4];
        out[pos++] = hexChars[bytes[i] & 0x0F];
    }
    out[pos] = '\0';
}

const char* resultToText(uint8_t result) {
    switch (result) {
        case RESULT_GRANTED: return "granted";
        case RESULT_UNKNOWN: return "unknown";
        case RESULT_EXPIRED: return "expired";
        case RESULT_SCHEDULE: return "schedule";
        case RESULT_MANUAL: return "manual";
        default: return "unknown";
    }
}
const char* directionToText(uint8_t direction) { return direction == DIR_OUT ? "out" : "in"; }
const char* modeToText(uint8_t mode) { return mode == 0 ? "online" : "offline"; }
const char* timeSourceToText(uint8_t source) {
    switch (source) { case TSRC_NTP: return "ntp"; case TSRC_RTC: return "rtc"; default: return "invalid"; }
}

bool compareAclRecords(const AclRecord& a, const AclRecord& b) {
    if (a.uidLen != b.uidLen) return a.uidLen < b.uidLen;
    return memcmp(a.uid, b.uid, a.uidLen) < 0;
}

// ============================================================
// 5. HARDWARE CONTROL
// ============================================================
void grantAccess() {
    isDenySequenceActive = false;
    digitalWrite(RED_LED_PIN, LOW);
    isRelayActive = true;
    relayStartTime = millis();
    digitalWrite(RELAY_PIN, HIGH);
    digitalWrite(GREEN_LED_PIN, HIGH);
    isSuccessBeepActive = true;
    successBeepStartTime = millis();
    digitalWrite(BUZZER_PIN, HIGH);
}

void denyAccess() {
    if (isRelayActive) return;
    isDenySequenceActive = true;
    denyBeepCount = 0;
    denyLedState = true;
    lastDenyStepTime = millis();
    digitalWrite(RED_LED_PIN, HIGH);
    digitalWrite(BUZZER_PIN, HIGH);
}

void handleHardwareTimers() {
    const unsigned long now = millis();
    if (isRelayActive && now - relayStartTime >= RELAY_DURATION_MS) {
        isRelayActive = false;
        digitalWrite(RELAY_PIN, LOW);
        digitalWrite(GREEN_LED_PIN, LOW);
    }
    if (isSuccessBeepActive && now - successBeepStartTime >= SUCCESS_BEEP_MS) {
        isSuccessBeepActive = false;
        digitalWrite(BUZZER_PIN, LOW);
    }
    if (isDenySequenceActive && now - lastDenyStepTime >= DENY_STEP_MS) {
        lastDenyStepTime = now;
        if (denyLedState) {
            digitalWrite(RED_LED_PIN, LOW);
            digitalWrite(BUZZER_PIN, LOW);
            denyLedState = false;
            denyBeepCount++;
        } else {
            if (denyBeepCount < 3) {
                digitalWrite(RED_LED_PIN, HIGH);
                digitalWrite(BUZZER_PIN, HIGH);
                denyLedState = true;
            } else {
                isDenySequenceActive = false;
            }
        }
    }
}

// ============================================================
// 6. ACL & FILE SYSTEM
// ============================================================
void loadAclToRAM() {
    File file = LittleFS.open("/database.bin", FILE_READ);
    if (!file) { 
        Serial.println("ERROR: database.bin unavailable. No ACL loaded."); 
        return; 
    }

    size_t fileSize = file.size();
    if (fileSize % sizeof(AclRecord) != 0) {
        Serial.println("WARNING: database.bin size is not a multiple of AclRecord size.");
    }
    size_t recordCount = fileSize / sizeof(AclRecord);

    std::vector<AclRecord> newList;
    newList.reserve(recordCount);

    AclRecord record;
    while (file.read(reinterpret_cast<uint8_t*>(&record), sizeof(AclRecord)) == sizeof(AclRecord)) {
        newList.push_back(record);
    }
    file.close();

    std::sort(newList.begin(), newList.end(), compareAclRecords);

    if (xSemaphoreTake(aclMutex, portMAX_DELAY) == pdTRUE) {
        aclList.swap(newList);
        xSemaphoreGive(aclMutex);
    } else {
        Serial.println("ERROR: Could not acquire ACL mutex to swap in new list.");
        return;
    }

    Serial.printf("Binary ACL loaded: %d records\n", aclList.size());
}

uint8_t evaluateAccess(const uint8_t* scannedUid, uint8_t uidLen, const DateTime& now) {
    AclRecord target = {};
    memcpy(target.uid, scannedUid, uidLen);
    target.uidLen = uidLen;

    uint8_t result = RESULT_UNKNOWN;

    if (xSemaphoreTake(aclMutex, pdMS_TO_TICKS(100)) == pdTRUE) {
        auto it = std::lower_bound(aclList.begin(), aclList.end(), target, compareAclRecords);
        
        // 1. UID Existence Check
        if (it == aclList.end() || target.uidLen != it->uidLen || memcmp(target.uid, it->uid, target.uidLen) != 0) {
            result = RESULT_UNKNOWN;

        // 2. Expiration Check
        } else if (now.unixtime() > it->valid_to) {
            result = RESULT_EXPIRED;

        // 3. Floor Bitmask Check
        } else if ((it->floor_mask & (1UL << FLOOR_NUMBER)) == 0) {
            result = RESULT_UNKNOWN; 

        // 4. Schedule Window Check (Cross-midnight & UTC-safe)
        } else if (!(it->win_start_m == 0 && it->win_end_m == 1440)) {
            uint16_t currentMinute = (now.hour() * 60) + now.minute();
            bool inWindow = (it->win_start_m <= it->win_end_m)
                ? (currentMinute >= it->win_start_m && currentMinute <= it->win_end_m)
                : (currentMinute >= it->win_start_m || currentMinute <= it->win_end_m);

            result = inWindow ? RESULT_GRANTED : RESULT_SCHEDULE;

        // 5. Full-Day Access Allowed
        } else {
            result = RESULT_GRANTED;
        }

        xSemaphoreGive(aclMutex);
    } else {
        Serial.println("ERROR: Could not acquire ACL mutex.");
    }

    return result;
}

// ============================================================
// 7. QUEUE MANAGEMENT
// ============================================================
uint32_t queueDistance(uint32_t r, uint32_t w) { return (w >= r) ? w - r : (MAX_EVENTS - r + w); }

bool queueIsEmpty() {
    portENTER_CRITICAL(&queueMux);
    bool empty = (queueCount == 0);
    portEXIT_CRITICAL(&queueMux);
    return empty;
}

bool evictOldestIfFull() {
    bool wasFull = false;
    portENTER_CRITICAL(&queueMux);
    if (queueCount >= MAX_EVENTS) {
        readPointer = (readPointer + 1) % MAX_EVENTS;
        wasFull = true;
    }
    portEXIT_CRITICAL(&queueMux);
    return wasFull;
}

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

bool readEventRecord(uint32_t index, AccessRecord& record) {
    File file = openEventFile(FILE_READ);
    if (!file) return false;
    uint32_t offset = index * RECORD_SIZE;
    if (file.size() < offset + RECORD_SIZE || !file.seek(offset, SeekSet)) { file.close(); return false; }
    size_t readBytes = file.read(reinterpret_cast<uint8_t*>(&record), sizeof(record));
    file.close();
    return readBytes == sizeof(record);
}

void rebuildQueueState() {
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

void saveCheckpoint(bool force = false) {
    if (!force && eventsSinceCheckpoint < CHECKPOINT_EVENT_INTERVAL && acksSinceCheckpoint < CHECKPOINT_ACK_INTERVAL) return;
    preferences.putUInt("readPtr", readPointer);
    preferences.putUInt("writePtr", writePointer);
    preferences.putUInt("qCount", queueCount);
    preferences.putUInt("seq", globalSequence);
    preferences.putUInt("aclVer", currentAclVersion);
    eventsSinceCheckpoint = 0; acksSinceCheckpoint = 0;
}

bool logAccess(const DateTime& now, const uint8_t* uidBytes, uint8_t uidLen, uint8_t direction, uint8_t resultCode) {
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
    record.mode = mqtt.connected() ? 0 : 1;
    record.tsrc = currentTimeSource;
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

// ============================================================
// 8a. OTA FIRMWARE UPDATE
// ============================================================
bool parseHttpUrl(const String& url, String& host, uint16_t& port, String& path) {
    if (!url.startsWith("http://")) return false;
    String rest = url.substring(7);
    int slashIdx = rest.indexOf('/');
    String hostPort = (slashIdx == -1) ? rest : rest.substring(0, slashIdx);
    path = (slashIdx == -1) ? "/" : rest.substring(slashIdx);

    int colonIdx = hostPort.indexOf(':');
    if (colonIdx == -1) {
        host = hostPort;
        port = 80;
    } else {
        host = hostPort.substring(0, colonIdx);
        port = (uint16_t)hostPort.substring(colonIdx + 1).toInt();
    }
    return host.length() > 0;
}

bool performOTA(const String& url, const String& expectedMd5, uint32_t expectedSize) {
    String host, path;
    uint16_t port;
    if (!parseHttpUrl(url, host, port, path)) {
        Serial.println("OTA: invalid URL (must be http://host[:port]/path).");
        return false;
    }
    if (expectedMd5.length() != 32) {
        Serial.println("OTA: expected md5 must be 32 hex characters.");
        return false;
    }

    EthernetClient otaClient;
    Serial.printf("OTA: connecting to %s:%u\n", host.c_str(), port);
    if (!otaClient.connect(host.c_str(), port)) {
        Serial.println("OTA: connection failed.");
        return false;
    }

    otaClient.printf("GET %s HTTP/1.1\r\nHost: %s\r\nConnection: close\r\n\r\n", path.c_str(), host.c_str());

    unsigned long headerWaitStart = millis();
    String statusLine = otaClient.readStringUntil('\n');
    if (statusLine.indexOf(" 200 ") == -1) {
        Serial.printf("OTA: unexpected HTTP status: %s\n", statusLine.c_str());
        otaClient.stop();
        return false;
    }

    long contentLength = -1;
    while (otaClient.connected() && (millis() - headerWaitStart < OTA_STALL_TIMEOUT_MS)) {
        String line = otaClient.readStringUntil('\n');
        if (line.startsWith("Content-Length:")) {
            contentLength = line.substring(16).toInt();
        }
        if (line == "\r" || line.length() == 0) break;
    }

    if (contentLength <= 0) {
        Serial.println("OTA: missing/invalid Content-Length.");
        otaClient.stop();
        return false;
    }
    if (expectedSize > 0 && (uint32_t)contentLength != expectedSize) {
        Serial.printf("OTA: WARNING - server said size=%u, Content-Length=%ld. Using Content-Length.\n",
                      expectedSize, contentLength);
    }

    if (!Update.begin(contentLength)) {
        Serial.printf("OTA: Update.begin() failed: %s\n", Update.errorString());
        otaClient.stop();
        return false;
    }
    if (!Update.setMD5(expectedMd5.c_str())) {
        Serial.println("OTA: Update.setMD5() rejected the provided hash.");
        Update.abort();
        otaClient.stop();
        return false;
    }

    uint8_t buf[OTA_CHUNK_SIZE];
    uint32_t totalWritten = 0;
    unsigned long lastDataMs = millis();
    unsigned long downloadStart = millis();

    while (totalWritten < (uint32_t)contentLength) {
        esp_task_wdt_reset();

        if (millis() - downloadStart > OTA_TOTAL_TIMEOUT_MS) {
            Serial.println("OTA: overall timeout exceeded, aborting.");
            Update.abort();
            otaClient.stop();
            return false;
        }

        int available = otaClient.available();
        if (available > 0) {
            int toRead = min(available, (int)sizeof(buf));
            int len = otaClient.read(buf, toRead);
            if (len > 0) {
                if (Update.write(buf, len) != (size_t)len) {
                    Serial.printf("OTA: flash write failed: %s\n", Update.errorString());
                    Update.abort();
                    otaClient.stop();
                    return false;
                }
                totalWritten += len;
                lastDataMs = millis();
            }
        } else if (!otaClient.connected()) {
            Serial.println("OTA: connection closed before download completed.");
            Update.abort();
            otaClient.stop();
            return false;
        } else if (millis() - lastDataMs > OTA_STALL_TIMEOUT_MS) {
            Serial.println("OTA: stalled (no data), aborting.");
            Update.abort();
            otaClient.stop();
            return false;
        }
    }
    otaClient.stop();

    if (!Update.end(true)) {
        Serial.printf("OTA: finalize/verify failed: %s\n", Update.errorString());
        return false;
    }

    Serial.printf("OTA: success, %u bytes written and verified.\n", totalWritten);
    return true;
}

// ============================================================
// 8. MQTT & NETWORKING
// ============================================================
void mqttCallback(MQTTClient *client, char topic[], char bytes[], int length) {
    String topicStr = topic;

    if (topicStr == TOPIC_EVENT_ACK) {
        JsonDocument doc;
        if (deserializeJson(doc, bytes, length)) return;
        pendingAckSeq = doc["ack_seq"] | 0UL;
        ackReceived = true;

    } else if (topicStr == TOPIC_ACL) {
        // Binary ACL payload reception
        if (length >= (int)sizeof(AclHeader)) {
            pendingAclBytes.assign((uint8_t*)bytes, (uint8_t*)bytes + length);
            aclMessageReceived = true;
        }

    } else if (topicStr == TOPIC_CMD) {
        String payload = String(bytes, length);
        Serial.println("Remote command received: " + payload);

        if (payload.startsWith("{")) {
            JsonDocument cmdDoc;
            if (deserializeJson(cmdDoc, payload)) {
                Serial.println("Invalid command JSON.");
                mqtt.publish(TOPIC_CMD_RES, "cmd_failed_bad_json", false, 1);
                return;
            }

            uint32_t seq = cmdDoc["seq"] | 0UL;
            const char* subCmd = cmdDoc["cmd"] | "";
            uint32_t cmdTs = cmdDoc["ts"] | 0UL;

            if (seq <= lastCmdSeq && seq != 0) {
                Serial.printf("Duplicate command seq=%u ignored.\n", seq);
                mqtt.publish(TOPIC_CMD_RES, "cmd_duplicate_ignored", false, 1);
                return;
            }

            DateTime now = rtcNowSafe();
            if (currentTimeSource != TSRC_INVALID && cmdTs > 0) {
                if (now.unixtime() > (cmdTs + 15)) {
                    Serial.printf("Expired command '%s' discarded.\n", subCmd);
                    mqtt.publish(TOPIC_CMD_RES, "cmd_expired_discarded", false, 1);
                    lastCmdSeq = seq;
                    return;
                }
            }

            lastCmdSeq = seq;

            if (strcmp(subCmd, "open") == 0) {
                static const uint8_t remoteUid[7] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};
                bool logged = logAccess(now, remoteUid, 7, DIR_IN, RESULT_MANUAL);
                grantAccess();
                mqtt.publish(TOPIC_CMD_RES, logged ? "open_ok" : "open_ok_unlogged", false, 1);
                if (!logged) Serial.println("WARNING: Remote open succeeded but event logging failed.");

            } else if (strcmp(subCmd, "reboot") == 0) {
                mqtt.publish(TOPIC_CMD_RES, "rebooting", false, 1);
                rebootPending = true;
                rebootRequestedAt = millis();

            } else if (strcmp(subCmd, "sync") == 0) {
                currentAclVersion = 0;
                preferences.putUInt("aclVer", 0);
                mqtt.subscribe(TOPIC_ACL, 1);
                mqtt.publish(TOPIC_CMD_RES, "sync_triggered", false, 1);

            } else if (strcmp(subCmd, "settime") == 0) {
                uint32_t newTs = cmdDoc["ts"] | 0UL;
                if (newTs >= 1735689600UL && newTs <= 2051222400UL) {
                    rtcAdjustSafe(DateTime(newTs));
                    currentTimeSource = TSRC_RTC;
                    lastNtpSync = millis();
                    mqtt.publish(TOPIC_CMD_RES, "settime_ok", false, 1);
                    Serial.printf("RTC time updated via backend command to: %lu\n", newTs);
                } else {
                    mqtt.publish(TOPIC_CMD_RES, "settime_failed_invalid_ts", false, 1);
                }

            } else if (strcmp(subCmd, "ota") == 0) {
                String otaUrl = cmdDoc["url"] | "";
                String otaMd5 = cmdDoc["md5"] | "";
                uint32_t otaSize = cmdDoc["size"] | 0UL;

                if (otaUrl.length() == 0 || otaMd5.length() != 32) {
                    mqtt.publish(TOPIC_CMD_RES, "ota_failed_bad_request", false, 1);
                    return;
                }

                mqtt.publish(TOPIC_CMD_RES, "ota_downloading", false, 1);
                bool ok = performOTA(otaUrl, otaMd5, otaSize);

                if (ok) {
                    mqtt.publish(TOPIC_CMD_RES, "ota_ok_rebooting", false, 1);
                    rebootPending = true;
                    rebootRequestedAt = millis();
                } else {
                    mqtt.publish(TOPIC_CMD_RES, "ota_failed", false, 1);
                }
            }
        }
    }
}

bool processPendingAck(bool currentlyWaiting) {
    if (!currentlyWaiting || !ackReceived) return currentlyWaiting;
    ackReceived = false;

    if (queueIsEmpty()) return false;
    AccessRecord record;
    if (!readEventRecord(readPointer, record) || !isRecordValid(record)) return currentlyWaiting;

    if (record.seq == pendingAckSeq) {
        portENTER_CRITICAL(&queueMux);
        readPointer = (readPointer + 1) % MAX_EVENTS;
        if (queueCount > 0) queueCount--;
        portEXIT_CRITICAL(&queueMux);
        acksSinceCheckpoint++;
        Serial.printf("ACK accepted seq=%d\n", pendingAckSeq);
        saveCheckpoint(false);
        return false;
    }
    return currentlyWaiting;
}

bool buildEventPayload(const AccessRecord& record, char* buffer, size_t bufferSize) {
    char uidHex[15];
    bytesToHex(record.uid, record.uidLen, uidHex, sizeof(uidHex));

    JsonDocument doc;
    doc["seq"] = record.seq;
    doc["dev"] = DEVICE_ID;
    doc["uid"] = uidHex;
    doc["ts"] = record.ts;
    doc["tsrc"] = timeSourceToText(record.tsrc);
    doc["floor"] = record.floor;
    doc["dir"] = directionToText(record.dir);
    doc["res"] = resultToText(record.result);
    doc["mode"] = modeToText(record.mode);
    doc["fw"] = FW_VERSION;
    return serializeJson(doc, buffer, bufferSize) > 0;
}

bool publishQueueHead() {
    if (!mqtt.connected() || queueIsEmpty()) return false;
    AccessRecord record;
    if (!readEventRecord(readPointer, record) || !isRecordValid(record)) return false;

    char payload[384];
    if (!buildEventPayload(record, payload, sizeof(payload))) return false;

    bool published = mqtt.publish(TOPIC_EVENT, payload, false, 1);
    if (published) Serial.printf("QoS1 publish seq=%d\n", record.seq);
    return published;
}

void processACLUpdate() {
    if (!aclMessageReceived) return;
    aclMessageReceived = false;

    if (pendingAclBytes.size() < sizeof(AclHeader)) {
        pendingAclBytes.clear();
        return;
    }

    AclHeader* hdr = reinterpret_cast<AclHeader*>(pendingAclBytes.data());
    uint32_t newVersion = hdr->ver;
    uint32_t cardCount = hdr->count;

    size_t expectedSize = sizeof(AclHeader) + (cardCount * sizeof(AclRecord));
    if (pendingAclBytes.size() != expectedSize) {
        Serial.printf("ERROR: Binary ACL size mismatch (got %u, expected %u)\n", 
                      pendingAclBytes.size(), expectedSize);
        pendingAclBytes.clear();
        return;
    }

    if (newVersion <= currentAclVersion) {
        pendingAclBytes.clear();
        return;
    }

    File dbFile = LittleFS.open("/database.tmp", FILE_WRITE);
    if (!dbFile) {
        Serial.println("ERROR: Cannot open /database.tmp for writing.");
        pendingAclBytes.clear();
        return;
    }

    // Write all records directly to flash in one contiguous operation
    const uint8_t* recordsPtr = pendingAclBytes.data() + sizeof(AclHeader);
    size_t bytesToWrite = cardCount * sizeof(AclRecord);

    if (bytesToWrite > 0) {
        dbFile.write(recordsPtr, bytesToWrite);
    }
    dbFile.flush();
    dbFile.close();

    // Free reception buffer immediately
    pendingAclBytes.clear();
    pendingAclBytes.shrink_to_fit();

    // Atomic file swap
    if (LittleFS.exists("/database.bin")) LittleFS.rename("/database.bin", "/database.bak");
    if (!LittleFS.rename("/database.tmp", "/database.bin")) {
        Serial.println("ERROR: ACL file rename failed.");
        if (LittleFS.exists("/database.bak")) LittleFS.rename("/database.bak", "/database.bin");
        return;
    }
    if (LittleFS.exists("/database.bak")) LittleFS.remove("/database.bak");

    // Load newly saved binary records into RAM
    loadAclToRAM();
    currentAclVersion = newVersion;
    preferences.putUInt("aclVer", currentAclVersion);
    Serial.printf("Binary ACL updated: ver=%u, cards=%u (%u bytes)\n", 
                  currentAclVersion, cardCount, bytesToWrite);
}

// ============================================================
// 9. SENSORS & RFID
// ============================================================
void handleExitButton() {
    bool reading = digitalRead(EXIT_BUTTON_PIN);
    if (reading != lastExitButtonState) lastExitDebounceTime = millis();
    if (millis() - lastExitDebounceTime >= EXIT_DEBOUNCE_MS) {
        if (reading != stableExitButtonState) {
            stableExitButtonState = reading;
            if (stableExitButtonState == LOW && !isRelayActive) {
                static const uint8_t zeroUid[7] = {0};
                DateTime now = rtcNowSafe();
                if (logAccess(now, zeroUid, 7, DEVICE_DIR, RESULT_MANUAL)) {
                    grantAccess();
                    Serial.println("EXIT BUTTON -> GRANTED");
                } else {
                    denyAccess();
                    Serial.println("SYSTEM ERROR: Exit button logging failed.");
                }
            }
        }
    }
    lastExitButtonState = reading;
}

void handleRFID() {
    if (!rfid.PICC_IsNewCardPresent() || !rfid.PICC_ReadCardSerial()) return;

    uint8_t uidLen = rfid.uid.size;
    uint8_t uidBytes[7];
    memset(uidBytes, 0, sizeof(uidBytes));
    memcpy(uidBytes, rfid.uid.uidByte, min((size_t)uidLen, sizeof(uidBytes)));

    rfid.PICC_HaltA();
    rfid.PCD_StopCrypto1();

    unsigned long nowMillis = millis();
    bool sameCard = (uidLen == lastUidLen) && (memcmp(uidBytes, lastUid, uidLen) == 0);
    if (sameCard && nowMillis - lastScanTime < RFID_DEBOUNCE_MS) return;

    memcpy(lastUid, uidBytes, uidLen);
    lastUidLen = uidLen;
    lastScanTime = nowMillis;

    char uidHex[15];
    bytesToHex(uidBytes, uidLen, uidHex, sizeof(uidHex));
    Serial.print("RFID UID: ");
    Serial.println(uidHex);

    DateTime now = rtcNowSafe();
    uint8_t resultCode = evaluateAccess(uidBytes, uidLen, now);

    if (logAccess(now, uidBytes, uidLen, DEVICE_DIR, resultCode)) {
        if (resultCode == RESULT_GRANTED) {
            grantAccess();
        } else {
            denyAccess();
        }
    } else {
        denyAccess();
        Serial.println("SYSTEM ERROR: User denied due to logging failure.");
    }
}

// ============================================================
// 10. INITIALIZATION ROUTINES
// ============================================================
void initRFID() {
    hspi.begin(RFID_SCK_PIN, RFID_MISO_PIN, RFID_MOSI_PIN, RFID_SS_PIN);
    rfid.PCD_Init();
    delay(10);
    Serial.printf("MFRC522 firmware: 0x%02X\n", rfid.PCD_GetVersion());
}

void initRTC() {
    Wire.begin(I2C_SDA_PIN, I2C_SCL_PIN);
    if (!rtc.begin()) { Serial.println("ERROR: PCF8563 missing."); currentTimeSource = TSRC_INVALID; return; }
    if (rtc.lostPower()) {
        rtcAdjustSafe(DateTime(F(__DATE__), F(__TIME__)));
        currentTimeSource = TSRC_INVALID;
    } else {
        currentTimeSource = TSRC_RTC;
    }
}

void initFileSystem() {
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
}

void initEthernet() {
    Serial.println("=== W5500 INIT ===");

    pinMode(W5500_RST_PIN, OUTPUT);
    digitalWrite(W5500_RST_PIN, LOW);
    delay(100);
    digitalWrite(W5500_RST_PIN, HIGH);
    delay(500);

    Serial.println("Starting VSPI...");
    SPI.begin(W5500_SCK_PIN, W5500_MISO_PIN, W5500_MOSI_PIN, W5500_CS_PIN);
    pinMode(W5500_CS_PIN, OUTPUT);
    digitalWrite(W5500_CS_PIN, HIGH);
    Ethernet.init(W5500_CS_PIN);

    Serial.println("Calling Ethernet.begin()...");
    Ethernet.begin(mac, deviceIP, dnsIP, gatewayIP, subnetMask);

    Serial.print("IP: ");
    Serial.println(Ethernet.localIP());
}

void initMQTT() {
    mqtt.begin(mqttServer, MQTT_PORT, ethClient);
    mqtt.setOptions(30, false, 1000);
    mqtt.onMessageAdvanced(mqttCallback);
    mqtt.setWill(TOPIC_STATUS, "offline", true, 1);
}

// ============================================================
// 11. NETWORK TASK (Core 0)
// ============================================================
void networkTaskCode(void* parameter) {
    esp_task_wdt_add(NULL);

    initEthernet();
    timeClient.begin();
    initMQTT();

    unsigned long lastHeartbeat = millis();
    unsigned long lastReconnectAttempt = 0;
    unsigned long backoff = 1000;
    
    bool waitingForAck = false;
    unsigned long ackWaitStart = 0;
    unsigned long lastPublishTime = 0;

    for (;;) {
        esp_task_wdt_reset();
        unsigned long now = millis();

        if (rebootPending && (now - rebootRequestedAt >= 500)) {
            ESP.restart();
        }

        Ethernet.maintain();

        if (Ethernet.linkStatus() == LinkON) {
            static unsigned long lastNtpAttempt = 0;
            unsigned long ntpInterval = (currentTimeSource == TSRC_NTP) ? NTP_SYNC_INTERVAL_MS : 15000UL;

            if (lastNtpAttempt == 0 || now - lastNtpAttempt >= ntpInterval) {
                lastNtpAttempt = now;
                
                if (timeClient.forceUpdate()) {
                    unsigned long epoch = timeClient.getEpochTime();
                    
                    if (epoch >= 1735689600UL && epoch <= 2051222400UL) {
                        rtcAdjustSafe(DateTime(epoch));
                        currentTimeSource = TSRC_NTP;
                        lastNtpSync = now;
                    } else {
                        Serial.printf("WARNING: Bogus NTP epoch ignored: %lu\n", epoch);
                    }
                }
            }

            if (!mqtt.connected()) {
                if (now - lastReconnectAttempt >= backoff) {
                    if (mqtt.connect(DEVICE_ID)) {
                        backoff = 1000;
                        mqtt.publish(TOPIC_STATUS, "online", true, 1);
                        mqtt.subscribe(TOPIC_EVENT_ACK, 1);
                        mqtt.subscribe(TOPIC_ACL, 1);
                        mqtt.subscribe(TOPIC_CMD, 1);
                    } else {
                        backoff = min(backoff * 2, 60000UL);
                        backoff += random(0, 1000);
                    }
                    lastReconnectAttempt = now;
                }
            } else {
                mqtt.loop();
                waitingForAck = processPendingAck(waitingForAck);
                processACLUpdate();

                // Heartbeat
                if (now - lastHeartbeat >= HEARTBEAT_INTERVAL_MS) {
                    JsonDocument hb;
                    hb["uptime"] = millis() / 1000; 
                    
                    portENTER_CRITICAL(&queueMux);
                    hb["queue"] = queueCount; 
                    portEXIT_CRITICAL(&queueMux);
                    
                    hb["heap"] = ESP.getFreeHeap(); 
                    hb["rssi"] = 0;
                    hb["qOverflow"] = queueOverflowCount;

                    char hbPayload[128];
                    serializeJson(hb, hbPayload, sizeof(hbPayload));
                    mqtt.publish(TOPIC_HEARTBEAT, hbPayload, false, 0);
                    lastHeartbeat = now;
                }

                // Store-and-forward Processing
                if (!queueIsEmpty()) {
                    if (waitingForAck) {
                        if (now - ackWaitStart >= ACK_TIMEOUT_MS) waitingForAck = false;
                    } else if (now - lastPublishTime >= PUBLISH_RATE_LIMIT_MS) {
                        if (publishQueueHead()) {
                            waitingForAck = true;
                            ackWaitStart = now;
                            lastPublishTime = now;
                        }
                    }
                }
            }
        } else {
            currentTimeSource = TSRC_RTC;
        }

        saveCheckpoint(false);
        vTaskDelay(25 / portTICK_PERIOD_MS);
    }
}

// ============================================================
// 12. SETUP & LOOP (Core 1)
// ============================================================
void setup() {
    Serial.begin(115200);
    delay(1000);

    Serial.printf("Reset reason: %d\n", esp_reset_reason());
    
    esp_task_wdt_init(10, true);
    esp_task_wdt_add(NULL);

    digitalWrite(RELAY_PIN, LOW);
    digitalWrite(GREEN_LED_PIN, LOW);
    digitalWrite(BUZZER_PIN, LOW);
    digitalWrite(RED_LED_PIN, LOW);

    pinMode(RELAY_PIN, OUTPUT);
    pinMode(GREEN_LED_PIN, OUTPUT);
    pinMode(BUZZER_PIN, OUTPUT);
    pinMode(RED_LED_PIN, OUTPUT);
    pinMode(EXIT_BUTTON_PIN, INPUT);

    initFileSystem();

    preferences.begin("access_system", false);
    readPointer = preferences.getUInt("readPtr", 0);
    writePointer = preferences.getUInt("writePtr", 0);
    queueCount = preferences.getUInt("qCount", 0);
    globalSequence = preferences.getUInt("seq", 0);
    currentAclVersion = preferences.getUInt("aclVer", 0);

    if (readPointer >= MAX_EVENTS) readPointer = 0;
    if (writePointer >= MAX_EVENTS) writePointer = 0;

    aclMutex = xSemaphoreCreateMutex();
    rtcMutex = xSemaphoreCreateMutex();

    loadAclToRAM();
    initRTC();
    initRFID();
    rebuildQueueState();

    xTaskCreatePinnedToCore(networkTaskCode, "NetworkTask", 12000, nullptr, 1, &NetworkTask, 0);
    Serial.println("Setup complete.");
}

void loop() {
    esp_task_wdt_reset();
    handleHardwareTimers();
    handleExitButton();
    handleRFID();
    vTaskDelay(1 / portTICK_PERIOD_MS);
}