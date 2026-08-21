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
#define FW_VERSION "1.2.0"
#define DEVICE_ID "GATE-K3-01"
#define FLOOR_NUMBER 3

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
#define PUBLISH_RATE_LIMIT_MS     50UL // max 20 msgs/sec

// OTA. This is deliberately synchronous: the whole
// download+flash runs inside mqttCallback() on the network task (core 0),
// blocking MQTT keepalive/ACK processing for its duration. RFID/relay
// handling (handleRFID/handleExitButton, core 1) is completely unaffected -
// the door keeps working normally during an update, which is the guarantee
// that actually matters. A lapsed keepalive just triggers the existing
// reconnect-with-backoff afterward, already self-healing.
#define OTA_CHUNK_SIZE           512
#define OTA_STALL_TIMEOUT_MS   10000UL // no bytes received for this long -> abort
#define OTA_TOTAL_TIMEOUT_MS   60000UL // whole download taking longer than this -> abort

// Persistent queue
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
    uint8_t  uid[7];       // Up to 7-byte UID
    uint8_t  uidLen;       // Length of the UID (usually 4 or 7)
    uint32_t floor_mask;   // Bitmask for floors (e.g., bit 3 = floor 3)
    uint32_t valid_to;     // Unix timestamp for expiration (UTC)
    uint16_t win_start_m;  // Active window start (minutes from midnight. e.g. 07:00 = 420)
    uint16_t win_end_m;    // Active window end (minutes from midnight. e.g. 19:00 = 1140)
};
#pragma pack(pop)

static_assert(sizeof(AccessRecord) == RECORD_SIZE, "AccessRecord must be 32 bytes");

enum Direction : uint8_t { DIR_IN = 0, DIR_OUT = 1 };
enum ResultCode : uint8_t { RESULT_GRANTED = 0, RESULT_UNKNOWN = 1, RESULT_EXPIRED = 2, RESULT_SCHEDULE = 3, RESULT_MANUAL = 4 };
enum TimeSource : uint8_t { TSRC_NTP = 0, TSRC_RTC = 1, TSRC_INVALID = 2 };

// ============================================================
// 3. GLOBAL OBJECTS
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

MQTTClient mqtt(4096);
TaskHandle_t NetworkTask = nullptr;

// Network Config
byte mac[] = { 0x00, 0x1A, 0x2B, 0x3C, 0x4D, 0x5E };
IPAddress deviceIP(192, 168, 11, 155);
IPAddress dnsIP(192, 168, 10, 1);
IPAddress gatewayIP(192, 168, 10, 1);
IPAddress subnetMask(255, 255, 254, 0);
IPAddress mqttServer(192, 168, 10, 250);
const uint16_t MQTT_PORT = 1883;

// Topics
const char* TOPIC_EVENT     = "pdks/merkez/dev/GATE-K3-01/event";
const char* TOPIC_EVENT_ACK = "pdks/merkez/dev/GATE-K3-01/event/ack";
const char* TOPIC_STATUS    = "pdks/merkez/dev/GATE-K3-01/status";
const char* TOPIC_HEARTBEAT = "pdks/merkez/dev/GATE-K3-01/hb";
const char* TOPIC_ACL       = "pdks/merkez/cfg/acl";
const char* TOPIC_CMD     = "pdks/merkez/dev/GATE-K3-01/cmd";
const char* TOPIC_CMD_RES = "pdks/merkez/dev/GATE-K3-01/cmd/res";

// RAM State
uint32_t readPointer = 0, writePointer = 0, globalSequence = 0;
uint32_t currentAclVersion = 0, queueCount = 0;
uint32_t queueOverflowCount = 0; // number of unacked records evicted to make room
// Set by the remote "reboot" command; consumed non-blockingly in the network
// task loop. The rest of this firmware deliberately never calls delay() (see
// project spec section 2.1/9 - it breaks MQTT keepalive and RFID responsiveness),
// so a reboot request can't just block for 500ms waiting for "rebooting" to
// flush onto the wire either.
volatile bool rebootPending = false;
unsigned long rebootRequestedAt = 0;
uint32_t eventsSinceCheckpoint = 0, acksSinceCheckpoint = 0;
std::vector<AclRecord> aclList;

// FreeRTOS Synchronization
portMUX_TYPE queueMux = portMUX_INITIALIZER_UNLOCKED;
SemaphoreHandle_t aclMutex = NULL;

// Helper comparator for sorting and binary search
bool compareAclRecords(const AclRecord& a, const AclRecord& b) {
    if (a.uidLen != b.uidLen) return a.uidLen < b.uidLen;
    return memcmp(a.uid, b.uid, a.uidLen) < 0;
}
uint8_t currentTimeSource = TSRC_RTC;
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
String pendingAclPayload;

// ============================================================
// 4. HELPERS (CRC, UID, Formatting)
// ============================================================
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

// Allocation-free hex helpers: bytes <-> hex text, no String involved anywhere.
uint8_t hexNibble(char c) {
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    return 0;
}

// Parses up to maxLen bytes of hex text (e.g. "04A2B3C1") into byteArray.
void hexToBytes(const char* hex, size_t hexLen, uint8_t* byteArray, uint8_t maxLen) {
    memset(byteArray, 0, maxLen);
    for (size_t i = 0; i + 1 < hexLen && (i / 2) < maxLen; i += 2) {
        byteArray[i / 2] = (hexNibble(hex[i]) << 4) | hexNibble(hex[i + 1]);
    }
}

// Writes uppercase hex text for `len` bytes into out (out must be at least 2*len+1 bytes).
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
    // Switch to binary file
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

    // Build the new list off to the side, without touching the shared aclList or
    // holding aclMutex at all. File I/O + sort can take a noticeable amount of time
    // once the card list grows, and evaluateAccess() (RFID hot path, core 1) only
    // waits 100ms for the mutex before treating a legitimate card as "unknown".
    // Holding the mutex for the whole reload risked spuriously denying a real
    // cardholder mid-reload.
    std::vector<AclRecord> newList;
    newList.reserve(recordCount); // Pre-allocate memory to prevent fragmentation

    AclRecord record;
    while (file.read(reinterpret_cast<uint8_t*>(&record), sizeof(AclRecord)) == sizeof(AclRecord)) {
        newList.push_back(record);
    }
    file.close();

    std::sort(newList.begin(), newList.end(), compareAclRecords);

    // The actual swap-in is just an exchange of a few pointers/sizes on the vector
    // (O(1)), so the critical section is now genuinely tiny - evaluateAccess() will
    // never see a multi-millisecond stall waiting on this mutex.
    if (xSemaphoreTake(aclMutex, portMAX_DELAY) == pdTRUE) {
        aclList.swap(newList);
        xSemaphoreGive(aclMutex);
    } else {
        Serial.println("ERROR: Could not acquire ACL mutex to swap in new list.");
        return;
    }
    // newList now holds the old data (or is empty on first load) and is freed here.

    Serial.printf("Binary ACL loaded: %d records\n", aclList.size());
}

uint8_t evaluateAccess(const uint8_t* scannedUid, uint8_t uidLen, const DateTime& now) {
    AclRecord target = {};
    memcpy(target.uid, scannedUid, uidLen);
    target.uidLen = uidLen;

    uint8_t result = RESULT_UNKNOWN;

    // Take mutex with a 100ms timeout so we don't block the hardware loop forever
    if (xSemaphoreTake(aclMutex, pdMS_TO_TICKS(100)) == pdTRUE) {
        auto it = std::lower_bound(aclList.begin(), aclList.end(), target, compareAclRecords);
        
        if (it == aclList.end() || target.uidLen != it->uidLen || memcmp(target.uid, it->uid, target.uidLen) != 0) {
            result = RESULT_UNKNOWN;
        } else if (now.unixtime() > it->valid_to) {
            result = RESULT_EXPIRED;
        } else if ((it->floor_mask & (1UL << FLOOR_NUMBER)) == 0) {
            result = RESULT_UNKNOWN; 
        } else {
            uint16_t current_minutes = (now.hour() * 60) + now.minute();
            if (current_minutes < it->win_start_m || current_minutes >= it->win_end_m) {
                result = RESULT_SCHEDULE;
            } else {
                result = RESULT_GRANTED;
            }
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
bool queueIsFull() { 
    portENTER_CRITICAL(&queueMux);
    bool full = (queueCount >= MAX_EVENTS);
    portEXIT_CRITICAL(&queueMux);
    return full; 
}

bool queueIsEmpty() {
    portENTER_CRITICAL(&queueMux);
    bool empty = (queueCount == 0);
    portEXIT_CRITICAL(&queueMux);
    return empty;
}

// When the queue is full, drop the single oldest unacknowledged record to make room
// for the new one, instead of refusing the write. Doors must keep working even during
// an extended outage; sacrificing the oldest unsent record is the documented trade-off
// readPointer is normally only mutated by the network task
// (on ACK) - this is the one place it's also mutated from the RFID/exit-button
// path, so it must go through queueMux like every other cross-core queue update.
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
        if ((i & 0x3FF) == 0) esp_task_wdt_reset(); // her 1024 kayıtta bir watchdog'u besle
    }
    file.close();

    if (newestIndex < 0) {
        readPointer = 0; writePointer = 0; queueCount = 0; return;
    }

    writePointer = (static_cast<uint32_t>(newestIndex) + 1) % MAX_EVENTS;
    globalSequence = max(globalSequence, newestSeq);
    if (readPointer >= MAX_EVENTS) readPointer = 0;

    portENTER_CRITICAL(&queueMux);
    queueCount = queueDistance(readPointer, writePointer);
    if (queueCount > MAX_EVENTS) queueCount = validCount;
    uint32_t safeQueueCount = queueCount;
    portEXIT_CRITICAL(&queueMux);

    Serial.printf("Queue rebuilt. read=%d write=%d count=%d\n", readPointer, writePointer, safeQueueCount);
}

void saveCheckpoint(bool force = false) {
    if (!force && eventsSinceCheckpoint < CHECKPOINT_EVENT_INTERVAL && acksSinceCheckpoint < CHECKPOINT_ACK_INTERVAL) return;
    preferences.putUInt("readPtr", readPointer);
    preferences.putUInt("writePtr", writePointer);
    preferences.putUInt("seq", globalSequence);
    preferences.putUInt("aclVer", currentAclVersion);
    eventsSinceCheckpoint = 0; acksSinceCheckpoint = 0;
}

bool logAccess(const DateTime& now, const uint8_t* uidBytes, uint8_t uidLen, uint8_t direction, uint8_t resultCode) {
    bool overwroteOldest = evictOldestIfFull();
    if (overwroteOldest) {
        queueOverflowCount++;
        Serial.printf("WARNING: Queue full - oldest unacknowledged event overwritten (total overflow=%u)\n", queueOverflowCount);
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
        // Note: if overwroteOldest is true here, readPointer has already advanced past
        // the evicted slot even though the replacement write failed - a rare double-
        // fault (queue full + flash I/O error at the same time) that trades a single
        // stale record for keeping the door responsive. Documented, not auto-recovered.
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
// Splits "http://host[:port]/path" into its parts. TLS isn't supported here,
// matching MQTT's own current lack of TLS (FR-17 also still pending) - both
// are fine for a private LAN, neither is fine to expose beyond one.
// Uses String since this runs once per OTA attempt (a rare, deliberately
// triggered admin action), not per-scan - the heap-fragmentation risk that
// ruled String out of the RFID/ACL hot paths doesn't apply here.
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

// Downloads the firmware at `url` and flashes it via the Update library.
// expectedMd5 must be exactly 32 hex chars; expectedSize is a sanity check
// against the server's own record of the file, separate from whatever
// Content-Length the HTTP response itself reports.
//
// Safety model: Update.setMD5() is checked automatically inside Update.end(),
// and the new partition is only marked bootable if that check (and the write
// itself) fully succeeds. A corrupted/truncated/wrong-file download leaves
// the currently-running firmware completely untouched - there is no partial
// or "maybe corrupt" state the device can end up booting into from this
// function failing partway through.
//
// Known limitation: this verifies the bytes weren't corrupted in transit,
// not who produced them - there's no code signing here. It also doesn't
// implement post-boot crash rollback (CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE
// is a platformio.ini/sdkconfig-level setting, not something this function
// can control) - if a bad-but-intact binary boots and then crashes, ESP-IDF's
// default behavior applies, which depends on partition/rollback config this
// firmware doesn't assume.
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

    // --- Read status line + headers ---
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
        if (line == "\r" || line.length() == 0) break; // blank line = end of headers
    }

    if (contentLength <= 0) {
        Serial.println("OTA: missing/invalid Content-Length.");
        otaClient.stop();
        return false;
    }
    if (expectedSize > 0 && (uint32_t)contentLength != expectedSize) {
        // Not necessarily fatal (the server's stored metadata could be
        // stale), but worth surfacing rather than silently trusting either
        // number - proceed using what the HTTP response itself reports,
        // since that's what will actually be written.
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

    // --- Stream body straight into flash ---
    uint8_t buf[OTA_CHUNK_SIZE];
    uint32_t totalWritten = 0;
    unsigned long lastDataMs = millis();
    unsigned long downloadStart = millis();

    while (totalWritten < (uint32_t)contentLength) {
        esp_task_wdt_reset(); // this loop can easily run longer than the 10s WDT timeout

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

    // Update.end(true) finalizes the write AND checks the MD5 set above -
    // the new partition is only marked bootable if both pass.
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
void mqttCallback(String& topic, String& payload) {
    if (topic == TOPIC_EVENT_ACK) {
        JsonDocument doc;
        if (deserializeJson(doc, payload)) { Serial.println("Invalid ACK JSON."); return; }
        pendingAckSeq = doc["ack_seq"] | 0UL;
        ackReceived = true;
    } else if (topic == TOPIC_ACL) {
        pendingAclPayload = payload;
        aclMessageReceived = true;
    } else if (topic == TOPIC_CMD) {
        Serial.println("Remote command received: " + payload);
        
        if (payload == "open") {
            // Write before actuate, same as every card scan (handleRFID) and
            // the exit button (handleExitButton) - the project's core rule is
            // that a record must never wait in RAM while the relay has
            // already fired, since a power loss in between would lose the
            // event with no trace it ever happened. The previous order here
            // (grantAccess() then logAccess()) inverted that for exactly this
            // one path.
            static const uint8_t remoteUid[7] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};
            bool logged = logAccess(rtc.now(), remoteUid, 7, DIR_IN, RESULT_MANUAL);

            // This is a deliberate operator action, not an unauthenticated
            // scan - still open the door even if the audit write failed
            // (e.g. a rare double-fault with the queue), but say so clearly
            // rather than silently reporting "open_ok" either way.
            grantAccess();
            mqtt.publish(TOPIC_CMD_RES, logged ? "open_ok" : "open_ok_unlogged", false, 1);
            if (!logged) Serial.println("WARNING: Remote open succeeded but the event was not logged.");
            
        } else if (payload == "reboot") {
            mqtt.publish(TOPIC_CMD_RES, "rebooting", false, 1);
            // Actual restart happens non-blockingly in the network task loop,
            // giving the MQTT client a chance to flush "rebooting" onto the
            // wire first - see the note by rebootPending's declaration for
            // why this can't just be a delay(500) here.
            rebootPending = true;
            rebootRequestedAt = millis();
            
        } else if (payload == "sync") {
            // Zeroing currentAclVersion alone was a no-op while connected: it
            // only takes effect on the *next* genuinely new ACL publish from
            // the panel, or the *next* reconnect - neither of which is
            // "on-demand" the way this command is supposed to be. Retained
            // messages are only (re)delivered on a SUBSCRIBE packet, and this
            // device was already subscribed, so nothing was actually
            // triggered to be resent.
            // Re-subscribing fixes that: per the MQTT spec, a SUBSCRIBE -
            // even to a topic the client is already subscribed to - always
            // redelivers that topic's current retained message. Combined with
            // zeroing the version (so whatever comes back is guaranteed to be
            // treated as newer, forcing a genuine re-parse even if the
            // version number turns out unchanged), this recovers from a
            // corrupted or stale local copy, not just "fetch it if newer".
            currentAclVersion = 0;
            preferences.putUInt("aclVer", 0);
            mqtt.subscribe(TOPIC_ACL, 1);
            mqtt.publish(TOPIC_CMD_RES, "sync_triggered", false, 1);

        } else if (payload.startsWith("{")) {
            // OTA (and any future structured command) arrives as JSON rather
            // than a bare word, since it needs more than one piece of data.
            // The existing open/reboot/sync commands stay plain strings -
            // this is additive, not a protocol-wide change.
            JsonDocument cmdDoc;
            if (deserializeJson(cmdDoc, payload)) {
                Serial.println("Invalid command JSON.");
                mqtt.publish(TOPIC_CMD_RES, "cmd_failed_bad_json", false, 1);
                return;
            }
            const char* subCmd = cmdDoc["cmd"] | "";

            if (strcmp(subCmd, "ota") == 0) {
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
                    // Reuses the same non-blocking reboot path as the "reboot"
                    // command above, giving this ack a chance to flush first.
                    rebootPending = true;
                    rebootRequestedAt = millis();
                } else {
                    mqtt.publish(TOPIC_CMD_RES, "ota_failed", false, 1);
                    // Current firmware is untouched either way - see the
                    // safety-model note above performOTA().
                }
            }
        }
    }
}

// Returns boolean indicating if a message is currently waiting for ack
bool processPendingAck(bool currentlyWaiting) {
    if (!ackReceived) return currentlyWaiting;
    ackReceived = false;

    if (queueIsEmpty()) return currentlyWaiting;
    AccessRecord record;
    if (!readEventRecord(readPointer, record) || !isRecordValid(record)) return currentlyWaiting;

    if (record.seq == pendingAckSeq) {
        readPointer = (readPointer + 1) % MAX_EVENTS;
        portENTER_CRITICAL(&queueMux);
        if (queueCount > 0) queueCount--;
        portEXIT_CRITICAL(&queueMux);
        acksSinceCheckpoint++;
        Serial.printf("ACK accepted seq=%d\n", pendingAckSeq);
        saveCheckpoint(false);
        return false; // No longer waiting for this ACK
    }
    return currentlyWaiting;
}

bool buildEventPayload(const AccessRecord& record, char* buffer, size_t bufferSize) {
    char uidHex[15];
    bytesToHex(record.uid, record.uidLen, uidHex, sizeof(uidHex));

    JsonDocument doc;
    doc["seq"] = record.seq;
    doc["dev"] = DEVICE_ID;
    doc["uid"] = uidHex; // ArduinoJson copies this into its own pool immediately
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

    JsonDocument doc; 
    if (deserializeJson(doc, pendingAclPayload)) { Serial.println("ACL JSON parse failed."); return; }

    uint32_t newVersion = doc["ver"] | 0UL;
    if (newVersion <= currentAclVersion) return;

    File dbFile = LittleFS.open("/database.tmp", FILE_WRITE);
    if (!dbFile) { Serial.println("ERROR: ACL temp file unavailable."); return; }

    JsonArray cards = doc["cards"].as<JsonArray>();
    for (JsonVariant card : cards) {
        AclRecord record = {};
        
        const char* uidCstr = card["uid"] | "";
        size_t uidCstrLen = strlen(uidCstr);
        record.uidLen = min(uidCstrLen / 2, (size_t)7);
        hexToBytes(uidCstr, uidCstrLen, record.uid, 7);
        
        // Parse floors into a bitmask (e.g., [1, 3] sets bits 1 and 3)
        JsonArray floors = card["floors"].as<JsonArray>();
        for (JsonVariant f : floors) {
            uint8_t floorNum = f.as<uint8_t>();
            if (floorNum < 32) record.floor_mask |= (1UL << floorNum);
        }
        
        // Default to max uint32 if valid_to is missing
        record.valid_to = card["valid_to"] | 0xFFFFFFFF; 
        
        // Parse time window "07:00-19:00" into minutes from midnight
        const char* win = card["win"] | "";
        int startH, startM, endH, endM;
        if (strlen(win) == 11 && sscanf(win, "%d:%d-%d:%d", &startH, &startM, &endH, &endM) == 4) {
            record.win_start_m = (startH * 60) + startM;
            record.win_end_m = (endH * 60) + endM;
        } else {
            // Default to 24 hours if missing or invalid
            record.win_start_m = 0;
            record.win_end_m = 1440;
        }

        dbFile.write(reinterpret_cast<const uint8_t*>(&record), sizeof(AclRecord));
    }
    dbFile.flush(); 
    dbFile.close();

    // Atomic file swap mechanism
    if (LittleFS.exists("/database.bin")) {
        LittleFS.rename("/database.bin", "/database.bak");
    }
    
    if (!LittleFS.rename("/database.tmp", "/database.bin")) { 
        Serial.println("ERROR: ACL rename failed."); 
        // Rollback on failure
        if (LittleFS.exists("/database.bak")) LittleFS.rename("/database.bak", "/database.bin");
        return; 
    }
    
    // Clean up backup on success
    if (LittleFS.exists("/database.bak")) LittleFS.remove("/database.bak");

    loadAclToRAM();
    currentAclVersion = newVersion;
    preferences.putUInt("aclVer", currentAclVersion);
    Serial.printf("ACL updated to version %d\n", currentAclVersion);
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
                if (logAccess(rtc.now(), zeroUid, 7, DIR_OUT, RESULT_MANUAL)) {
                    grantAccess();
                    Serial.println("EXIT BUTTON -> GRANTED");
                } else {
                    // Provide physical feedback if logging fails
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

    uint8_t resultCode = evaluateAccess(uidBytes, uidLen, rtc.now());

    if (logAccess(rtc.now(), uidBytes, uidLen, DIR_IN, resultCode)) {
        if (resultCode == RESULT_GRANTED) {
            grantAccess();
        } else {
            denyAccess();
        }
    } else {
        // Provide physical feedback if the queue is full or FS fails
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
        rtc.adjust(DateTime(F(__DATE__), F(__TIME__)));
        currentTimeSource = TSRC_INVALID;
    } else {
        currentTimeSource = TSRC_RTC;
    }
}

void initFileSystem() {
    if (!LittleFS.begin(true)) { Serial.println("ERROR: LittleFS mount failed."); return; }
    
    // Touch the binary file if it doesn't exist
    if (!LittleFS.exists("/database.bin")) {
        File file = LittleFS.open("/database.bin", FILE_WRITE);
        if (file) file.close(); 
    }
    if (!LittleFS.exists(EVENT_FILE)) { 
        File file = LittleFS.open(EVENT_FILE, FILE_WRITE); 
        if(file) file.close(); 
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

    SPI.begin(
        W5500_SCK_PIN,
        W5500_MISO_PIN,
        W5500_MOSI_PIN,
        W5500_CS_PIN
    );

    pinMode(
        W5500_CS_PIN,
        OUTPUT
    );

    digitalWrite(
        W5500_CS_PIN,
        HIGH
    );

    Ethernet.init(
        W5500_CS_PIN
    );

    Serial.println("Calling Ethernet.begin()...");

    Ethernet.begin(
        mac,
        deviceIP,
        dnsIP,
        gatewayIP,
        subnetMask
    );

    EthernetHardwareStatus hw =
        Ethernet.hardwareStatus();

    Serial.print("Hardware status: ");

    switch (hw) {

        case EthernetW5500:
            Serial.println("W5500 DETECTED");
            break;

        case EthernetW5100:
            Serial.println("W5100 DETECTED");
            break;

        case EthernetW5200:
            Serial.println("W5200 DETECTED");
            break;

        default:
            Serial.println("NO ETHERNET HARDWARE");
            break;
    }

    Serial.print("Link status: ");

    switch (Ethernet.linkStatus()) {

        case LinkON:
            Serial.println("LINK ON");
            break;

        case LinkOFF:
            Serial.println("LINK OFF");
            break;

        default:
            Serial.println("LINK UNKNOWN");
            break;
    }

    Serial.print("IP: ");
    Serial.println(Ethernet.localIP());

    Serial.print("Gateway: ");
    Serial.println(Ethernet.gatewayIP());

    Serial.print("Subnet: ");
    Serial.println(Ethernet.subnetMask());
}

void initMQTT() {
    mqtt.begin(mqttServer, MQTT_PORT, ethClient);
    mqtt.setOptions(30, false, 1000);
    mqtt.onMessage(mqttCallback);
    mqtt.setWill(TOPIC_STATUS, "offline", true, 1);
}

// ============================================================
// 11. NETWORK TASK (Core 0)
// ============================================================
void networkTaskCode(void* parameter) {
    esp_task_wdt_add(NULL); // Subscribe this task to the watchdog

    initEthernet();
    timeClient.begin();
    initMQTT();

    unsigned long lastHeartbeat = millis();
    unsigned long lastReconnectAttempt = 0;
    unsigned long backoff = 1000;
    
    // Store & Forward State Variables
    bool waitingForAck = false;
    unsigned long ackWaitStart = 0;
    unsigned long lastPublishTime = 0;

    for (;;) {
        esp_task_wdt_reset(); // Feed the watchdog
        unsigned long now = millis();

        // Non-blocking counterpart to the removed delay(500) before ESP.restart():
        // give the "rebooting" ack ~500ms to actually flush onto the wire via
        // mqtt.loop() below on prior iterations, then restart. Checked every
        // iteration of this loop (short period), so the actual delay past 500ms
        // is negligible.
        if (rebootPending && (now - rebootRequestedAt >= 500)) {
            ESP.restart();
        }

        Ethernet.maintain();

        if (Ethernet.linkStatus() == LinkON) {
            timeClient.update();
            if (timeClient.isTimeSet() && (lastNtpSync == 0 || now - lastNtpSync >= NTP_SYNC_INTERVAL_MS)) {
                rtc.adjust(DateTime(timeClient.getEpochTime()));
                currentTimeSource = TSRC_NTP;
                lastNtpSync = now;
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
                        backoff += random(0, 1000); // jitter, avoids synchronized reconnect storms across gate units
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
                    mqtt.publish(TOPIC_HEARTBEAT, hbPayload, false, 0); // QoS 0 as required
                    lastHeartbeat = now;
                }

                // Store-and-forward Processing with Timeout & Rate Limiting
                if (!queueIsEmpty()) {
                    if (waitingForAck) {
                        if (now - ackWaitStart >= ACK_TIMEOUT_MS) waitingForAck = false; // Timeout reached, retry
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
            // Revert to RTC tracking if network link is physically down
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
    // ESP_RST_BROWNOUT = 8 → brownout
    
    // Hardware Watchdog - 10 Seconds Timeout
    esp_task_wdt_init(10, true);
    esp_task_wdt_add(NULL);

    // 1. Pre-load the safe LOW state into the register
    digitalWrite(RELAY_PIN, LOW);
    digitalWrite(GREEN_LED_PIN, LOW);
    digitalWrite(BUZZER_PIN, LOW);
    digitalWrite(RED_LED_PIN, LOW);

    // 2. NOW activate the output drivers
    pinMode(RELAY_PIN, OUTPUT);
    pinMode(GREEN_LED_PIN, OUTPUT);
    pinMode(BUZZER_PIN, OUTPUT);
    pinMode(RED_LED_PIN, OUTPUT);
    pinMode(EXIT_BUTTON_PIN, INPUT);

    initFileSystem();

    preferences.begin("access_system", false);
    readPointer = preferences.getUInt("readPtr", 0);
    writePointer = preferences.getUInt("writePtr", 0);
    globalSequence = preferences.getUInt("seq", 0);
    currentAclVersion = preferences.getUInt("aclVer", 0);

    if (readPointer >= MAX_EVENTS) readPointer = 0;
    if (writePointer >= MAX_EVENTS) writePointer = 0;

    // Initialize the ACL Mutex
    aclMutex = xSemaphoreCreateMutex();

    loadAclToRAM();
    initRTC();
    initRFID();
    rebuildQueueState();

    xTaskCreatePinnedToCore(networkTaskCode, "NetworkTask", 12000, nullptr, 1, &NetworkTask, 0);
    Serial.println("Setup complete.");
}

void loop() {
    esp_task_wdt_reset(); // Feed the watchdog
    handleHardwareTimers();
    handleExitButton();
    handleRFID();
    vTaskDelay(1 / portTICK_PERIOD_MS);
}