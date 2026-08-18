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

// Increased to 4096 bytes to safely handle retained ACL JSON payloads
MQTTClient mqtt(4096);
TaskHandle_t NetworkTask = nullptr;

// Network Config
byte mac[] = { 0x00, 0x1A, 0x2B, 0x3C, 0x4D, 0x5E };
IPAddress deviceIP(192, 168, 1, 50);
IPAddress dnsIP(192, 168, 1, 1);
IPAddress gatewayIP(192, 168, 1, 1);
IPAddress subnetMask(255, 255, 255, 0);
IPAddress mqttServer(192, 168, 1, 100);
const uint16_t MQTT_PORT = 1883;

// Topics
const char* TOPIC_EVENT     = "pdks/merkez/dev/GATE-K3-01/event";
const char* TOPIC_EVENT_ACK = "pdks/merkez/dev/GATE-K3-01/event/ack";
const char* TOPIC_STATUS    = "pdks/merkez/dev/GATE-K3-01/status";
const char* TOPIC_HEARTBEAT = "pdks/merkez/dev/GATE-K3-01/hb";
const char* TOPIC_ACL       = "pdks/merkez/cfg/acl";

// RAM State
uint32_t readPointer = 0, writePointer = 0, globalSequence = 0;
uint32_t currentAclVersion = 0, queueCount = 0;
uint32_t eventsSinceCheckpoint = 0, acksSinceCheckpoint = 0;
std::vector<String> aclList;
uint8_t currentTimeSource = TSRC_RTC;
unsigned long lastNtpSync = 0;

// Hardware & Debounce State
bool isRelayActive = false, isSuccessBeepActive = false, isDenySequenceActive = false;
unsigned long relayStartTime = 0, successBeepStartTime = 0, lastDenyStepTime = 0;
uint8_t denyBeepCount = 0;
bool denyLedState = false;
bool lastExitButtonState = HIGH, stableExitButtonState = HIGH;
unsigned long lastExitDebounceTime = 0;
String lastScannedUID = "";
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

void stringToBytes(const String& hexString, uint8_t* byteArray, uint8_t maxLen) {
    memset(byteArray, 0, maxLen);
    for (uint16_t i = 0; i + 1 < hexString.length() && (i / 2) < maxLen; i += 2) {
        byteArray[i / 2] = static_cast<uint8_t>(strtol(hexString.substring(i, i + 2).c_str(), nullptr, 16));
    }
}

String uidToString() {
    String uid;
    for (byte i = 0; i < rfid.uid.size; i++) {
        if (rfid.uid.uidByte[i] < 0x10) uid += "0";
        uid += String(rfid.uid.uidByte[i], HEX);
    }
    uid.toUpperCase();
    return uid;
}

String recordUIDToString(const AccessRecord& record) {
    String uid;
    for (uint8_t i = 0; i < record.uidLen && i < 7; i++) {
        if (record.uid[i] < 0x10) uid += "0";
        uid += String(record.uid[i], HEX);
    }
    uid.toUpperCase();
    return uid;
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
    aclList.clear();
    File file = LittleFS.open("/database.txt", FILE_READ);
    if (!file) { Serial.println("ERROR: database.txt unavailable."); return; }
    while (file.available()) {
        String line = file.readStringUntil('\n');
        line.trim();
        line.toUpperCase();
        if (line.length() > 0) aclList.push_back(line);
    }
    file.close();
    std::sort(aclList.begin(), aclList.end());
    Serial.printf("ACL loaded: %d records\n", aclList.size());
}

bool isCardAuthorized(String uid) {
    uid.trim();
    uid.toUpperCase();
    return std::binary_search(aclList.begin(), aclList.end(), uid);
}

// ============================================================
// 7. QUEUE MANAGEMENT
// ============================================================
uint32_t queueDistance(uint32_t r, uint32_t w) { return (w >= r) ? w - r : (MAX_EVENTS - r + w); }
bool queueIsFull() { return queueCount >= MAX_EVENTS; }
bool queueIsEmpty() {
    return queueCount == 0;
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

    for (uint32_t i = 0; i < MAX_EVENTS; i++) {
        AccessRecord record;
        if (!readEventRecord(i, record) || !isRecordValid(record)) continue;
        validCount++;
        if (record.seq > newestSeq) { newestSeq = record.seq; newestIndex = static_cast<int>(i); }
    }

    if (newestIndex < 0) {
        readPointer = 0; writePointer = 0; queueCount = 0; return;
    }

    writePointer = (static_cast<uint32_t>(newestIndex) + 1) % MAX_EVENTS;
    globalSequence = max(globalSequence, newestSeq);
    if (readPointer >= MAX_EVENTS) readPointer = 0;
    
    queueCount = queueDistance(readPointer, writePointer);
    if (queueCount > MAX_EVENTS) queueCount = validCount;
    Serial.printf("Queue rebuilt. read=%d write=%d count=%d\n", readPointer, writePointer, queueCount);
}

void saveCheckpoint(bool force = false) {
    if (!force && eventsSinceCheckpoint < CHECKPOINT_EVENT_INTERVAL && acksSinceCheckpoint < CHECKPOINT_ACK_INTERVAL) return;
    preferences.putUInt("readPtr", readPointer);
    preferences.putUInt("writePtr", writePointer);
    preferences.putUInt("seq", globalSequence);
    preferences.putUInt("aclVer", currentAclVersion);
    eventsSinceCheckpoint = 0; acksSinceCheckpoint = 0;
}

bool logAccess(const DateTime& now, const String& scannedUID, uint8_t direction, uint8_t resultCode) {
    if (queueIsFull()) { Serial.println("QUEUE FULL - EVENT DROPPED"); return false; }

    AccessRecord record = {};
    record.seq = ++globalSequence;
    record.ts = now.unixtime();
    record.uidLen = min(static_cast<int>(scannedUID.length() / 2), 7);
    stringToBytes(scannedUID, record.uid, 7);
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
    queueCount++;
    eventsSinceCheckpoint++;
    Serial.printf("EVENT STORED seq=%d\n", record.seq);
    saveCheckpoint(false);
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
        if (queueCount > 0) queueCount--;
        acksSinceCheckpoint++;
        Serial.printf("ACK accepted seq=%d\n", pendingAckSeq);
        saveCheckpoint(false);
        return false; // No longer waiting for this ACK
    }
    return currentlyWaiting;
}

bool buildEventPayload(const AccessRecord& record, char* buffer, size_t bufferSize) {
    JsonDocument doc;
    doc["seq"] = record.seq;
    doc["dev"] = DEVICE_ID;
    doc["uid"] = recordUIDToString(record);
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

    JsonDocument doc; // Note: with Mqtt Buffer at 4096, ArduinoJson v7 automatically manages memory
    if (deserializeJson(doc, pendingAclPayload)) { Serial.println("ACL JSON parse failed."); return; }

    uint32_t newVersion = doc["ver"] | 0UL;
    if (newVersion <= currentAclVersion) return;

    File dbFile = LittleFS.open("/database.tmp", FILE_WRITE);
    if (!dbFile) { Serial.println("ERROR: ACL temp file unavailable."); return; }

    JsonArray cards = doc["cards"].as<JsonArray>();
    for (JsonVariant card : cards) {
        String uid = card["uid"].as<String>();
        uid.trim(); uid.toUpperCase();
        if (uid.length() > 0) dbFile.println(uid);
    }
    dbFile.flush(); dbFile.close();

    if (LittleFS.exists("/database.txt")) LittleFS.remove("/database.txt");
    if (!LittleFS.rename("/database.tmp", "/database.txt")) { Serial.println("ERROR: ACL rename failed."); return; }

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
                if (logAccess(rtc.now(), "00000000000000", DIR_OUT, RESULT_MANUAL)) {
                    grantAccess();
                    Serial.println("EXIT BUTTON -> GRANTED");
                }
            }
        }
    }
    lastExitButtonState = reading;
}

void handleRFID() {
    if (!rfid.PICC_IsNewCardPresent() || !rfid.PICC_ReadCardSerial()) return;
    String scannedUID = uidToString();
    rfid.PICC_HaltA();
    rfid.PCD_StopCrypto1();

    unsigned long nowMillis = millis();
    if (scannedUID == lastScannedUID && nowMillis - lastScanTime < RFID_DEBOUNCE_MS) return;

    lastScannedUID = scannedUID;
    lastScanTime = nowMillis;
    Serial.println("RFID UID: " + scannedUID);

    bool authorized = isCardAuthorized(scannedUID);
    if (logAccess(rtc.now(), scannedUID, DIR_IN, authorized ? RESULT_GRANTED : RESULT_UNKNOWN)) {
        authorized ? grantAccess() : denyAccess();
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
    if (!LittleFS.exists("/database.txt")) {
        File file = LittleFS.open("/database.txt", FILE_WRITE);
        if (file) { file.println("04A2B3C1D5E680"); file.close(); }
    }
    if (!LittleFS.exists(EVENT_FILE)) { File file = LittleFS.open(EVENT_FILE, FILE_WRITE); if(file) file.close(); }
}

void initEthernet() {
    pinMode(W5500_RST_PIN, OUTPUT);
    digitalWrite(W5500_RST_PIN, LOW); delay(2);
    digitalWrite(W5500_RST_PIN, HIGH); delay(200);

    SPI.begin(W5500_SCK_PIN, W5500_MISO_PIN, W5500_MOSI_PIN, W5500_CS_PIN);
    Ethernet.init(W5500_CS_PIN);
    Ethernet.begin(mac, deviceIP, dnsIP, gatewayIP, subnetMask);
    Serial.print("Ethernet IP: "); Serial.println(Ethernet.localIP());
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
                    } else {
                        backoff = min(backoff * 2, 60000UL);
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
                    hb["uptime"] = true; hb["queue"] = queueCount; 
                    hb["heap"] = ESP.getFreeHeap(); hb["rssi"] = 0;
                    String payload; serializeJson(hb, payload);
                    mqtt.publish(TOPIC_HEARTBEAT, payload, false, 1);
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
    
    // Hardware Watchdog - 10 Seconds Timeout
    esp_task_wdt_init(10, true);
    esp_task_wdt_add(NULL);

    pinMode(RELAY_PIN, OUTPUT);
    pinMode(BUZZER_PIN, OUTPUT);
    pinMode(GREEN_LED_PIN, OUTPUT);
    pinMode(RED_LED_PIN, OUTPUT);
    pinMode(EXIT_BUTTON_PIN, INPUT); // Requires external 10k pull-up

    digitalWrite(RELAY_PIN, LOW);
    digitalWrite(BUZZER_PIN, LOW);
    digitalWrite(GREEN_LED_PIN, LOW);
    digitalWrite(RED_LED_PIN, LOW);

    initFileSystem();

    preferences.begin("access_system", false);
    readPointer = preferences.getUInt("readPtr", 0);
    writePointer = preferences.getUInt("writePtr", 0);
    globalSequence = preferences.getUInt("seq", 0);
    currentAclVersion = preferences.getUInt("aclVer", 0);

    if (readPointer >= MAX_EVENTS) readPointer = 0;
    if (writePointer >= MAX_EVENTS) writePointer = 0;

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