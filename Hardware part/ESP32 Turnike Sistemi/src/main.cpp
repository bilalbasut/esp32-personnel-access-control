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

#include <MFRC522v2.h>
#include <MFRC522DriverSPI.h>
#include <MFRC522DriverPinSimple.h>

// ============================================================
// 1. CONFIGURATION
// ============================================================

#define FW_VERSION "1.2.0"

#define DEVICE_ID "GATE-K3-01"
#define FLOOR_NUMBER 3

// ---------- Hardware ----------
#define RELAY_PIN       32
#define BUZZER_PIN      33
#define GREEN_LED_PIN   25
#define RED_LED_PIN     17
#define EXIT_BUTTON_PIN 35

// ---------- W5500 / VSPI ----------
#define W5500_SCK_PIN   18
#define W5500_MISO_PIN  19
#define W5500_MOSI_PIN  23
#define W5500_CS_PIN    5
#define W5500_RST_PIN   4

// ---------- MFRC522 / HSPI ----------
#define RFID_SCK_PIN    14
#define RFID_MISO_PIN   27
#define RFID_MOSI_PIN   13
#define RFID_SS_PIN     15

// ---------- I2C ----------
#define I2C_SDA_PIN     21
#define I2C_SCL_PIN     22

// ---------- Timing ----------
#define RELAY_DURATION_MS       3000UL
#define SUCCESS_BEEP_MS          250UL
#define DENY_STEP_MS             150UL
#define RFID_DEBOUNCE_MS        5000UL
#define EXIT_DEBOUNCE_MS          50UL
#define HEARTBEAT_INTERVAL_MS  30000UL
#define NTP_SYNC_INTERVAL_MS 3600000UL

// ---------- Persistent queue ----------
#define EVENT_FILE "/events.bin"

// 20,000 records x 32 bytes = 640 KB
#define MAX_EVENTS 20000
#define RECORD_SIZE 32

// NVS is NOT updated on every event.
// A checkpoint is made after this many changes.
#define CHECKPOINT_EVENT_INTERVAL 64
#define CHECKPOINT_ACK_INTERVAL   16

// ============================================================
// 2. ACCESS RECORD
// ============================================================

#pragma pack(push, 1)

struct AccessRecord {
    uint32_t seq;          // 4
    uint32_t ts;           // 4
    uint8_t  uid[7];       // 7
    uint8_t  uidLen;       // 1
    uint8_t  dir;          // 1
    uint8_t  result;       // 1
    uint8_t  mode;         // 1
    uint8_t  tsrc;         // 1
    uint8_t  floor;        // 1
    uint8_t  reserved[9];  // 9
    uint16_t crc16;        // 2
};

#pragma pack(pop)

static_assert(
    sizeof(AccessRecord) == RECORD_SIZE,
    "AccessRecord must be exactly 32 bytes"
);

// ============================================================
// 3. ENUMS
// ============================================================

enum Direction : uint8_t {
    DIR_IN  = 0,
    DIR_OUT = 1
};

enum ResultCode : uint8_t {
    RESULT_GRANTED  = 0,
    RESULT_UNKNOWN  = 1,
    RESULT_EXPIRED  = 2,
    RESULT_SCHEDULE = 3,
    RESULT_MANUAL   = 4
};

enum TimeSource : uint8_t {
    TSRC_NTP     = 0,
    TSRC_RTC     = 1,
    TSRC_INVALID = 2
};

// ============================================================
// 4. GLOBAL OBJECTS
// ============================================================

Preferences preferences;

RTC_PCF8563 rtc;

SPIClass hspi(HSPI);

// MFRC522 uses HSPI
MFRC522DriverPinSimple rfidSS(RFID_SS_PIN);

MFRC522DriverSPI rfidDriver(
    rfidSS,
    hspi
);

MFRC522 rfid(rfidDriver);

// W5500 uses the ESP32 global SPI / VSPI
EthernetUDP ntpUDP;

NTPClient timeClient(
    ntpUDP,
    "pool.ntp.org",
    0,
    60000
);

EthernetClient ethClient;

// 256dpi MQTT library
MQTTClient mqtt(512);

// Network task
TaskHandle_t NetworkTask = nullptr;

// ============================================================
// 5. NETWORK CONFIGURATION
// ============================================================

byte mac[] = {
    0x00,
    0x1A,
    0x2B,
    0x3C,
    0x4D,
    0x5E
};

// Change these to match your LAN.
IPAddress deviceIP(
    192, 168, 1, 50
);

IPAddress dnsIP(
    192, 168, 1, 1
);

IPAddress gatewayIP(
    192, 168, 1, 1
);

IPAddress subnetMask(
    255, 255, 255, 0
);

IPAddress mqttServer(
    192, 168, 1, 100
);

const uint16_t MQTT_PORT = 1883;

// ============================================================
// 6. MQTT TOPICS
// ============================================================

const char* TOPIC_EVENT =
    "pdks/merkez/dev/GATE-K3-01/event";

const char* TOPIC_EVENT_ACK =
    "pdks/merkez/dev/GATE-K3-01/event/ack";

const char* TOPIC_STATUS =
    "pdks/merkez/dev/GATE-K3-01/status";

const char* TOPIC_HEARTBEAT =
    "pdks/merkez/dev/GATE-K3-01/hb";

const char* TOPIC_ACL =
    "pdks/merkez/cfg/acl";

// ============================================================
// 7. RAM STATE
// ============================================================

// Persistent queue indexes.
// These are RAM-first values.
// NVS only stores periodic checkpoints.
uint32_t readPointer  = 0;
uint32_t writePointer = 0;

uint32_t globalSequence = 0;

uint32_t currentAclVersion = 0;

// Number of records currently waiting for ACK.
// Calculated from RAM pointers.
uint32_t queueCount = 0;

// NVS checkpoint counters
uint32_t eventsSinceCheckpoint = 0;
uint32_t acksSinceCheckpoint = 0;

// ACL
std::vector<String> aclList;

// Time source
uint8_t currentTimeSource = TSRC_RTC;

unsigned long lastNtpSync = 0;

// ============================================================
// 8. HARDWARE STATE
// ============================================================

bool isRelayActive = false;
unsigned long relayStartTime = 0;

bool isSuccessBeepActive = false;
unsigned long successBeepStartTime = 0;

bool isDenySequenceActive = false;
unsigned long lastDenyStepTime = 0;

uint8_t denyBeepCount = 0;
bool denyLedState = false;

// ============================================================
// 9. EXIT BUTTON DEBOUNCE
// ============================================================

bool lastExitButtonState = HIGH;
bool stableExitButtonState = HIGH;

unsigned long lastExitDebounceTime = 0;

// ============================================================
// 10. RFID DEBOUNCE
// ============================================================

String lastScannedUID = "";
unsigned long lastScanTime = 0;

// ============================================================
// 11. MQTT CALLBACK FLAGS
// ============================================================

// IMPORTANT:
// We do NOT publish/subscribe from inside the MQTT callback.
// The callback only stores the received data.
// The network task processes it afterwards.

volatile bool ackReceived = false;
volatile uint32_t pendingAckSeq = 0;

volatile bool aclMessageReceived = false;

String pendingAclPayload;

// ============================================================
// 12. CRC16
// ============================================================

uint16_t calculateCRC16(
    const uint8_t* data,
    size_t length
) {
    uint16_t crc = 0xFFFF;

    for (size_t i = 0; i < length; i++) {
        crc ^= data[i];

        for (uint8_t bit = 0; bit < 8; bit++) {
            if (crc & 0x0001) {
                crc = (crc >> 1) ^ 0xA001;
            } else {
                crc >>= 1;
            }
        }
    }

    return crc;
}

uint16_t calculateRecordCRC(
    const AccessRecord& record
) {
    return calculateCRC16(
        reinterpret_cast<const uint8_t*>(&record),
        sizeof(AccessRecord) - sizeof(record.crc16)
    );
}

bool isRecordValid(
    const AccessRecord& record
) {
    if (record.seq == 0) {
        return false;
    }

    if (record.uidLen > 7) {
        return false;
    }

    return (
        calculateRecordCRC(record) ==
        record.crc16
    );
}

// ============================================================
// 13. UID HELPERS
// ============================================================

void stringToBytes(
    const String& hexString,
    uint8_t* byteArray,
    uint8_t maxLen
) {
    for (
        uint8_t i = 0;
        i < maxLen;
        i++
    ) {
        byteArray[i] = 0;
    }

    for (
        uint16_t i = 0;
        i + 1 < hexString.length() &&
        (i / 2) < maxLen;
        i += 2
    ) {
        String byteString =
            hexString.substring(i, i + 2);

        byteArray[i / 2] =
            static_cast<uint8_t>(
                strtol(
                    byteString.c_str(),
                    nullptr,
                    16
                )
            );
    }
}

String uidToString() {
    String uid;

    for (
        byte i = 0;
        i < rfid.uid.size;
        i++
    ) {
        if (rfid.uid.uidByte[i] < 0x10) {
            uid += "0";
        }

        uid += String(
            rfid.uid.uidByte[i],
            HEX
        );
    }

    uid.toUpperCase();

    return uid;
}

String recordUIDToString(
    const AccessRecord& record
) {
    String uid;

    for (
        uint8_t i = 0;
        i < record.uidLen &&
        i < 7;
        i++
    ) {
        if (record.uid[i] < 0x10) {
            uid += "0";
        }

        uid += String(
            record.uid[i],
            HEX
        );
    }

    uid.toUpperCase();

    return uid;
}

// ============================================================
// 14. RESULT / MODE / TIME SOURCE TEXT
// ============================================================

const char* resultToText(
    uint8_t result
) {
    switch (result) {
        case RESULT_GRANTED:
            return "granted";

        case RESULT_UNKNOWN:
            return "unknown";

        case RESULT_EXPIRED:
            return "expired";

        case RESULT_SCHEDULE:
            return "schedule";

        case RESULT_MANUAL:
            return "manual";

        default:
            return "unknown";
    }
}

const char* directionToText(
    uint8_t direction
) {
    return direction == DIR_OUT
        ? "out"
        : "in";
}

const char* modeToText(
    uint8_t mode
) {
    return mode == 0
        ? "online"
        : "offline";
}

const char* timeSourceToText(
    uint8_t source
) {
    switch (source) {
        case TSRC_NTP:
            return "ntp";

        case TSRC_RTC:
            return "rtc";

        default:
            return "invalid";
    }
}

// ============================================================
// 15. HARDWARE CONTROL
// ============================================================

void grantAccess() {

    isDenySequenceActive = false;

    digitalWrite(
        RED_LED_PIN,
        LOW
    );

    isRelayActive = true;
    relayStartTime = millis();

    digitalWrite(
        RELAY_PIN,
        HIGH
    );

    digitalWrite(
        GREEN_LED_PIN,
        HIGH
    );

    isSuccessBeepActive = true;
    successBeepStartTime = millis();

    digitalWrite(
        BUZZER_PIN,
        HIGH
    );
}

void denyAccess() {

    if (isRelayActive) {
        return;
    }

    isDenySequenceActive = true;

    denyBeepCount = 0;
    denyLedState = true;

    lastDenyStepTime = millis();

    digitalWrite(
        RED_LED_PIN,
        HIGH
    );

    digitalWrite(
        BUZZER_PIN,
        HIGH
    );
}

void handleHardwareTimers() {

    const unsigned long now =
        millis();

    // ---------- Relay ----------

    if (
        isRelayActive &&
        now - relayStartTime >=
            RELAY_DURATION_MS
    ) {

        isRelayActive = false;

        digitalWrite(
            RELAY_PIN,
            LOW
        );

        digitalWrite(
            GREEN_LED_PIN,
            LOW
        );
    }

    // ---------- Success beep ----------

    if (
        isSuccessBeepActive &&
        now - successBeepStartTime >=
            SUCCESS_BEEP_MS
    ) {

        isSuccessBeepActive = false;

        digitalWrite(
            BUZZER_PIN,
            LOW
        );
    }

    // ---------- Deny sequence ----------

    if (isDenySequenceActive) {

        if (
            now - lastDenyStepTime >=
            DENY_STEP_MS
        ) {

            lastDenyStepTime = now;

            if (denyLedState) {

                digitalWrite(
                    RED_LED_PIN,
                    LOW
                );

                digitalWrite(
                    BUZZER_PIN,
                    LOW
                );

                denyLedState = false;
                denyBeepCount++;

            } else {

                if (denyBeepCount < 3) {

                    digitalWrite(
                        RED_LED_PIN,
                        HIGH
                    );

                    digitalWrite(
                        BUZZER_PIN,
                        HIGH
                    );

                    denyLedState = true;

                } else {

                    isDenySequenceActive =
                        false;
                }
            }
        }
    }
}

// ============================================================
// 16. ACL
// ============================================================

void loadAclToRAM() {

    aclList.clear();

    File file =
        LittleFS.open(
            "/database.txt",
            FILE_READ
        );

    if (!file) {

        Serial.println(
            "ERROR: database.txt unavailable."
        );

        return;
    }

    while (file.available()) {

        String line =
            file.readStringUntil('\n');

        line.trim();
        line.toUpperCase();

        if (line.length() > 0) {
            aclList.push_back(line);
        }
    }

    file.close();

    std::sort(
        aclList.begin(),
        aclList.end()
    );

    Serial.print(
        "ACL loaded: "
    );

    Serial.println(
        aclList.size()
    );
}

bool isCardAuthorized(
    String uid
) {
    uid.trim();
    uid.toUpperCase();

    return std::binary_search(
        aclList.begin(),
        aclList.end(),
        uid
    );
}

// ============================================================
// 17. QUEUE HELPERS
// ============================================================

uint32_t queueDistance(
    uint32_t readIndex,
    uint32_t writeIndex
) {
    if (writeIndex >= readIndex) {
        return writeIndex - readIndex;
    }

    return (
        MAX_EVENTS -
        readIndex +
        writeIndex
    );
}

bool queueIsFull() {
    return queueCount >= MAX_EVENTS;
}

bool queueIsEmpty() {
    return readPointer == writePointer;
}

// ============================================================
// 18. OPEN EVENT FILE
// ============================================================

File openEventFile(
    const char* mode
) {
    return LittleFS.open(
        EVENT_FILE,
        mode
    );
}

// ============================================================
// 19. WRITE EVENT RECORD
// ============================================================

bool writeEventRecord(
    const AccessRecord& record,
    uint32_t index
) {

    File file =
        openEventFile("r+");

    if (!file) {

        // First creation
        file =
            openEventFile("w+");
    }

    if (!file) {

        Serial.println(
            "ERROR: Cannot open events.bin"
        );

        return false;
    }

    const uint32_t offset =
        index * RECORD_SIZE;

    if (!file.seek(
            offset,
            SeekSet
        )) {

        Serial.println(
            "ERROR: Queue seek failed."
        );

        file.close();

        return false;
    }

    const size_t written =
        file.write(
            reinterpret_cast<
                const uint8_t*
            >(&record),
            sizeof(record)
        );

    file.flush();
    file.close();

    return written ==
        sizeof(record);
}

// ============================================================
// 20. READ EVENT RECORD
// ============================================================

bool readEventRecord(
    uint32_t index,
    AccessRecord& record
) {

    File file =
        openEventFile(
            FILE_READ
        );

    if (!file) {
        return false;
    }

    const uint32_t offset =
        index * RECORD_SIZE;

    if (
        file.size() <
        offset + RECORD_SIZE
    ) {
        file.close();
        return false;
    }

    if (!file.seek(
            offset,
            SeekSet
        )) {

        file.close();
        return false;
    }

    const size_t readBytes =
        file.read(
            reinterpret_cast<
                uint8_t*
            >(&record),
            sizeof(record)
        );

    file.close();

    return readBytes ==
        sizeof(record);
}

// ============================================================
// 21. FIND QUEUE STATE AFTER REBOOT
// ============================================================

void rebuildQueueState() {

    uint32_t newestSeq = 0;
    int newestIndex = -1;

    uint32_t validCount = 0;

    for (
        uint32_t i = 0;
        i < MAX_EVENTS;
        i++
    ) {

        AccessRecord record;

        if (
            !readEventRecord(
                i,
                record
            )
        ) {
            continue;
        }

        if (!isRecordValid(record)) {
            continue;
        }

        validCount++;

        if (
            record.seq > newestSeq
        ) {
            newestSeq = record.seq;
            newestIndex =
                static_cast<int>(i);
        }
    }

    if (newestIndex < 0) {

        readPointer = 0;
        writePointer = 0;
        queueCount = 0;

        return;
    }

    writePointer =
        (
            static_cast<uint32_t>(
                newestIndex
            ) + 1
        ) % MAX_EVENTS;

    globalSequence =
        max(
            globalSequence,
            newestSeq
        );

    // NVS read pointer is only a checkpoint.
    // If it is behind, duplicates are harmless because
    // the server deduplicates by seq.
    if (
        readPointer >= MAX_EVENTS
    ) {
        readPointer = 0;
    }

    queueCount =
        queueDistance(
            readPointer,
            writePointer
        );

    if (
        queueCount > MAX_EVENTS
    ) {
        queueCount = validCount;
    }

    Serial.print(
        "Queue rebuilt. read="
    );
    Serial.print(readPointer);

    Serial.print(
        " write="
    );
    Serial.print(writePointer);

    Serial.print(
        " count="
    );
    Serial.println(queueCount);
}

// ============================================================
// 22. NVS CHECKPOINT
// ============================================================

void saveCheckpoint(
    bool force = false
) {

    if (
        !force &&
        eventsSinceCheckpoint <
            CHECKPOINT_EVENT_INTERVAL &&
        acksSinceCheckpoint <
            CHECKPOINT_ACK_INTERVAL
    ) {
        return;
    }

    preferences.putUInt(
        "readPtr",
        readPointer
    );

    preferences.putUInt(
        "writePtr",
        writePointer
    );

    preferences.putUInt(
        "seq",
        globalSequence
    );

    preferences.putUInt(
        "aclVer",
        currentAclVersion
    );

    eventsSinceCheckpoint = 0;
    acksSinceCheckpoint = 0;

    Serial.println(
        "NVS checkpoint saved."
    );
}

// ============================================================
// 23. LOG ACCESS
// ============================================================

bool logAccess(
    const DateTime& now,
    const String& scannedUID,
    uint8_t direction,
    uint8_t resultCode
) {

    if (queueIsFull()) {

        Serial.println(
            "QUEUE FULL - ACCESS EVENT NOT WRITTEN"
        );

        // Audit integrity is more important than
        // silently overwriting an unacknowledged event.
        return false;
    }

    AccessRecord record = {};

    globalSequence++;

    record.seq =
        globalSequence;

    record.ts =
        now.unixtime();

    record.uidLen =
        min(
            static_cast<int>(
                scannedUID.length() / 2
            ),
            7
        );

    stringToBytes(
        scannedUID,
        record.uid,
        7
    );

    record.dir =
        direction;

    record.result =
        resultCode;

    // This event was generated while MQTT
    // was connected or offline.
    record.mode =
        mqtt.connected()
            ? 0
            : 1;

    record.tsrc =
        currentTimeSource;

    record.floor =
        FLOOR_NUMBER;

    record.crc16 =
        calculateRecordCRC(
            record
        );

    if (
        !writeEventRecord(
            record,
            writePointer
        )
    ) {

        Serial.println(
            "ERROR: Event write failed."
        );

        globalSequence--;

        return false;
    }

    writePointer =
        (
            writePointer + 1
        ) % MAX_EVENTS;

    queueCount++;

    eventsSinceCheckpoint++;

    Serial.print(
        "EVENT STORED seq="
    );

    Serial.println(
        record.seq
    );

    // Important:
    // Event is physically stored before
    // the relay is activated.
    saveCheckpoint(false);

    return true;
}

// ============================================================
// 24. MQTT CALLBACK
// ============================================================

void mqttCallback(
    String& topic,
    String& payload
) {

    if (
        topic ==
        TOPIC_EVENT_ACK
    ) {

        JsonDocument doc;

        if (
            deserializeJson(
                doc,
                payload
            )
        ) {

            Serial.println(
                "Invalid ACK JSON."
            );

            return;
        }

        pendingAckSeq =
            doc["ack_seq"] |
            0UL;

        ackReceived = true;

        return;
    }

    if (
        topic ==
        TOPIC_ACL
    ) {

        pendingAclPayload =
            payload;

        aclMessageReceived =
            true;
    }
}

// ============================================================
// 25. PROCESS ACK
// ============================================================

void processPendingAck() {

    if (!ackReceived) {
        return;
    }

    ackReceived = false;

    const uint32_t ackSeq =
        pendingAckSeq;

    if (queueIsEmpty()) {
        return;
    }

    AccessRecord record;

    if (
        !readEventRecord(
            readPointer,
            record
        )
    ) {

        Serial.println(
            "ACK: Cannot read queue head."
        );

        return;
    }

    if (!isRecordValid(record)) {

        Serial.println(
            "ACK: Corrupt queue record."
        );

        // Do NOT silently advance.
        // Audit data must not disappear.
        return;
    }

    if (
        record.seq != ackSeq
    ) {

        Serial.print(
            "ACK mismatch. expected="
        );

        Serial.print(record.seq);

        Serial.print(
            " received="
        );

        Serial.println(ackSeq);

        return;
    }

    readPointer =
        (
            readPointer + 1
        ) % MAX_EVENTS;

    if (queueCount > 0) {
        queueCount--;
    }

    acksSinceCheckpoint++;

    Serial.print(
        "ACK accepted seq="
    );

    Serial.println(
        ackSeq
    );

    saveCheckpoint(false);
}

// ============================================================
// 26. MQTT PAYLOAD
// ============================================================

bool buildEventPayload(
    const AccessRecord& record,
    char* buffer,
    size_t bufferSize
) {

    JsonDocument doc;

    doc["seq"] =
        record.seq;

    doc["dev"] =
        DEVICE_ID;

    doc["uid"] =
        recordUIDToString(
            record
        );

    doc["ts"] =
        record.ts;

    doc["tsrc"] =
        timeSourceToText(
            record.tsrc
        );

    doc["floor"] =
        record.floor;

    doc["dir"] =
        directionToText(
            record.dir
        );

    doc["res"] =
        resultToText(
            record.result
        );

    doc["mode"] =
        modeToText(
            record.mode
        );

    doc["fw"] =
        FW_VERSION;

    return serializeJson(
        doc,
        buffer,
        bufferSize
    ) > 0;
}

// ============================================================
// 27. PUBLISH QUEUE HEAD - QoS 1
// ============================================================

bool publishQueueHead() {

    if (
        !mqtt.connected() ||
        queueIsEmpty()
    ) {
        return false;
    }

    AccessRecord record;

    if (
        !readEventRecord(
            readPointer,
            record
        )
    ) {

        Serial.println(
            "QUEUE: read failed."
        );

        return false;
    }

    if (
        !isRecordValid(record)
    ) {

        Serial.println(
            "QUEUE: CRC error."
        );

        return false;
    }

    char payload[384];

    if (
        !buildEventPayload(
            record,
            payload,
            sizeof(payload)
        )
    ) {

        Serial.println(
            "QUEUE: payload creation failed."
        );

        return false;
    }

    // QoS 1.
    // The library waits for PUBACK.
    const bool published =
        mqtt.publish(
            TOPIC_EVENT,
            payload,
            false,
            1
        );

    if (published) {

        Serial.print(
            "QoS1 publish successful seq="
        );

        Serial.println(
            record.seq
        );
    }

    return published;
}

// ============================================================
// 28. ACL PROCESSING
// ============================================================

void processACLUpdate() {

    if (!aclMessageReceived) {
        return;
    }

    aclMessageReceived = false;

    JsonDocument doc;

    DeserializationError error =
        deserializeJson(
            doc,
            pendingAclPayload
        );

    if (error) {

        Serial.println(
            "ACL JSON parse failed."
        );

        return;
    }

    uint32_t newVersion =
        doc["ver"] |
        0UL;

    if (
        newVersion <=
        currentAclVersion
    ) {

        Serial.println(
            "ACL already up to date."
        );

        return;
    }

    File dbFile =
        LittleFS.open(
            "/database.tmp",
            FILE_WRITE
        );

    if (!dbFile) {

        Serial.println(
            "ERROR: ACL temp file unavailable."
        );

        return;
    }

    JsonArray cards =
        doc["cards"].as<JsonArray>();

    for (
        JsonVariant card :
        cards
    ) {

        String uid =
            card["uid"].as<String>();

        uid.trim();
        uid.toUpperCase();

        if (
            uid.length() > 0
        ) {
            dbFile.println(uid);
        }
    }

    dbFile.flush();
    dbFile.close();

    // Replace old database only after
    // the new one has been successfully written.
    if (
        LittleFS.exists(
            "/database.txt"
        )
    ) {
        LittleFS.remove(
            "/database.txt"
        );
    }

    if (
        !LittleFS.rename(
            "/database.tmp",
            "/database.txt"
        )
    ) {

        Serial.println(
            "ERROR: ACL rename failed."
        );

        return;
    }

    loadAclToRAM();

    currentAclVersion =
        newVersion;

    // ACL version is not a per-event write,
    // so this NVS write is acceptable.
    preferences.putUInt(
        "aclVer",
        currentAclVersion
    );

    Serial.print(
        "ACL updated to version "
    );

    Serial.println(
        currentAclVersion
    );
}

// ============================================================
// 29. EXIT BUTTON
// ============================================================

void handleExitButton() {

    const bool reading =
        digitalRead(
            EXIT_BUTTON_PIN
        );

    if (
        reading !=
        lastExitButtonState
    ) {

        lastExitDebounceTime =
            millis();
    }

    if (
        millis() -
        lastExitDebounceTime >=
        EXIT_DEBOUNCE_MS
    ) {

        if (
            reading !=
            stableExitButtonState
        ) {

            stableExitButtonState =
                reading;

            if (
                stableExitButtonState ==
                LOW
            ) {

                if (!isRelayActive) {

                    DateTime now =
                        rtc.now();

                    // Manual OUT event.
                    // No RFID card was used.
                    const bool stored =
                        logAccess(
                            now,
                            "00000000000000",
                            DIR_OUT,
                            RESULT_MANUAL
                        );

                    if (stored) {

                        grantAccess();

                        Serial.println(
                            "EXIT BUTTON -> ACCESS GRANTED"
                        );
                    }
                }
            }
        }
    }

    lastExitButtonState =
        reading;
}

// ============================================================
// 30. RFID
// ============================================================

void handleRFID() {

    if (
        !rfid.PICC_IsNewCardPresent()
    ) {
        return;
    }

    if (
        !rfid.PICC_ReadCardSerial()
    ) {
        return;
    }

    String scannedUID =
        uidToString();

    rfid.PICC_HaltA();
    rfid.PCD_StopCrypto1();

    const unsigned long nowMillis =
        millis();

    // 5 second debounce
    if (
        scannedUID ==
            lastScannedUID &&
        nowMillis -
            lastScanTime <
            RFID_DEBOUNCE_MS
    ) {

        Serial.println(
            "RFID debounce."
        );

        return;
    }

    lastScannedUID =
        scannedUID;

    lastScanTime =
        nowMillis;

    Serial.print(
        "RFID UID: "
    );

    Serial.println(
        scannedUID
    );

    DateTime now =
        rtc.now();

    const bool authorized =
        isCardAuthorized(
            scannedUID
        );

    if (authorized) {

        const bool stored =
            logAccess(
                now,
                scannedUID,
                DIR_IN,
                RESULT_GRANTED
            );

        if (stored) {

            grantAccess();

            Serial.println(
                "ACCESS GRANTED"
            );
        }

    } else {

        const bool stored =
            logAccess(
                now,
                scannedUID,
                DIR_IN,
                RESULT_UNKNOWN
            );

        if (stored) {

            denyAccess();

            Serial.println(
                "ACCESS DENIED"
            );
        }
    }
}

// ============================================================
// 31. RFID INITIALIZATION
// ============================================================

void initRFID() {

    hspi.begin(
        RFID_SCK_PIN,
        RFID_MISO_PIN,
        RFID_MOSI_PIN,
        RFID_SS_PIN
    );

    rfid.PCD_Init();

    delay(10);

    Serial.print(
        "MFRC522 firmware: 0x"
    );

    Serial.println(
        (uint8_t)rfid.PCD_GetVersion(),
        HEX
    );
}

// ============================================================
// 32. RTC
// ============================================================

void initRTC() {

    Wire.begin(
        I2C_SDA_PIN,
        I2C_SCL_PIN
    );

    if (!rtc.begin()) {

        Serial.println(
            "ERROR: PCF8563 not found."
        );

        currentTimeSource =
            TSRC_INVALID;

        return;
    }

    if (
        rtc.lostPower()
    ) {

        Serial.println(
            "RTC lost power."
        );

        rtc.adjust(
            DateTime(
                F(__DATE__),
                F(__TIME__)
            )
        );

        currentTimeSource =
            TSRC_INVALID;

    } else {

        currentTimeSource =
            TSRC_RTC;
    }
}

// ============================================================
// 33. FILE SYSTEM
// ============================================================

void initFileSystem() {

    if (
        !LittleFS.begin(true)
    ) {

        Serial.println(
            "ERROR: LittleFS mount failed."
        );

        return;
    }

    if (
        !LittleFS.exists(
            "/database.txt"
        )
    ) {

        File file =
            LittleFS.open(
                "/database.txt",
                FILE_WRITE
            );

        if (file) {

            // Test UID.
            // Replace/remove for real deployment.
            file.println(
                "04A2B3C1D5E680"
            );

            file.close();
        }
    }

    // Create queue file if missing.
    if (
        !LittleFS.exists(
            EVENT_FILE
        )
    ) {

        File file =
            LittleFS.open(
                EVENT_FILE,
                FILE_WRITE
            );

        if (file) {
            file.close();
        }
    }
}

// ============================================================
// 34. W5500
// ============================================================

void initEthernet() {

    pinMode(
        W5500_RST_PIN,
        OUTPUT
    );

    digitalWrite(
        W5500_RST_PIN,
        LOW
    );

    // W5500 reset pulse.
    // This is initialization-only.
    delay(2);

    digitalWrite(
        W5500_RST_PIN,
        HIGH
    );

    delay(200);

    // Global SPI on ESP32 is VSPI.
    SPI.begin(
        W5500_SCK_PIN,
        W5500_MISO_PIN,
        W5500_MOSI_PIN,
        W5500_CS_PIN
    );

    Ethernet.init(
        W5500_CS_PIN
    );

    // Static network configuration.
    Ethernet.begin(
        mac,
        deviceIP,
        dnsIP,
        gatewayIP,
        subnetMask
    );

    Serial.print(
        "Ethernet IP: "
    );

    Serial.println(
        Ethernet.localIP()
    );
}

// ============================================================
// 35. NTP
// ============================================================

void updateTimeFromNTP() {

    if (
        !timeClient.isTimeSet()
    ) {
        return;
    }

    const unsigned long now =
        millis();

    if (
        lastNtpSync == 0 ||
        now - lastNtpSync >=
            NTP_SYNC_INTERVAL_MS
    ) {

        rtc.adjust(
            DateTime(
                timeClient.getEpochTime()
            )
        );

        currentTimeSource =
            TSRC_NTP;

        lastNtpSync =
            now;

        Serial.println(
            "RTC synchronized from NTP."
        );
    }
}

// ============================================================
// 36. MQTT SETUP
// ============================================================

void initMQTT() {

    mqtt.begin(
        mqttServer,
        MQTT_PORT,
        ethClient
    );

    mqtt.setOptions(
        30,     // keepAlive seconds
        false,  // cleanSession = false
        1000    // command timeout
    );

    mqtt.onMessage(
        mqttCallback
    );

    // LWT: offline
    mqtt.setWill(
        TOPIC_STATUS,
        "offline",
        true,
        1
    );
}

// ============================================================
// 37. MQTT CONNECT
// ============================================================

bool connectMQTT() {

    Serial.println(
        "Connecting MQTT..."
    );

    if (
        !mqtt.connect(
            DEVICE_ID
        )
    ) {

        Serial.println(
            "MQTT connection failed."
        );

        return false;
    }

    Serial.println(
        "MQTT connected."
    );

    // Online retained status
    mqtt.publish(
        TOPIC_STATUS,
        "online",
        true,
        1
    );

    mqtt.subscribe(
        TOPIC_EVENT_ACK,
        1
    );

    mqtt.subscribe(
        TOPIC_ACL,
        1
    );

    return true;
}

// ============================================================
// 38. NETWORK TASK
// ============================================================

void networkTaskCode(
    void* parameter
) {

    initEthernet();

    timeClient.begin();

    initMQTT();

    unsigned long lastHeartbeat =
        millis();

    unsigned long lastReconnectAttempt =
        0;

    unsigned long backoff =
        1000;

    for (;;) {

        const unsigned long now =
            millis();

        // ----------------------------------------------------
        // Ethernet maintenance
        // ----------------------------------------------------

        Ethernet.maintain();

        if (
            Ethernet.linkStatus() ==
            LinkON
        ) {

            // ------------------------------------------------
            // NTP
            // ------------------------------------------------

            timeClient.update();

            updateTimeFromNTP();

            // ------------------------------------------------
            // MQTT connection
            // ------------------------------------------------

            if (!mqtt.connected()) {

                if (
                    now -
                    lastReconnectAttempt >=
                    backoff
                ) {

                    if (
                        connectMQTT()
                    ) {

                        backoff =
                            1000;

                    } else {

                        backoff *= 2;

                        if (
                            backoff >
                            60000
                        ) {
                            backoff =
                                60000;
                        }
                    }

                    lastReconnectAttempt =
                        now;
                }

            } else {

                // ------------------------------------------------
                // MQTT loop
                // ------------------------------------------------

                mqtt.loop();

                // Callback only stores ACK/ACL data.
                processPendingAck();

                processACLUpdate();

                // ------------------------------------------------
                // Heartbeat
                // ------------------------------------------------

                if (
                    now -
                    lastHeartbeat >=
                    HEARTBEAT_INTERVAL_MS
                ) {

                    JsonDocument hb;

                    hb["uptime"] =
                        true;

                    hb["queue"] =
                        queueCount;

                    hb["heap"] =
                        ESP.getFreeHeap();

                    hb["rssi"] =
                        0;

                    String payload;

                    serializeJson(
                        hb,
                        payload
                    );

                    mqtt.publish(
                        TOPIC_HEARTBEAT,
                        payload,
                        false,
                        1
                    );

                    lastHeartbeat =
                        now;
                }

                // ------------------------------------------------
                // Store-and-forward
                // ------------------------------------------------

                if (
                    !queueIsEmpty()
                ) {

                    publishQueueHead();
                }
            }
        }

        // ----------------------------------------------------
        // Periodic NVS checkpoint even without MQTT
        // ----------------------------------------------------

        saveCheckpoint(false);

        // ----------------------------------------------------
        // FreeRTOS delay
        // ----------------------------------------------------

        vTaskDelay(
            25 /
            portTICK_PERIOD_MS
        );
    }
}

// ============================================================
// 39. SETUP
// ============================================================

void setup() {

    Serial.begin(
        115200
    );

    delay(1000);

    Serial.println();
    Serial.println(
        "================================"
    );
    Serial.println(
        "ESP32 PDKS GATE UNIT"
    );
    Serial.println(
        "VSPI  -> W5500"
    );
    Serial.println(
        "HSPI  -> MFRC522"
    );
    Serial.println(
        "MQTT  -> QoS 1"
    );
    Serial.println(
        "QUEUE -> LittleFS"
    );
    Serial.println(
        "================================"
    );

    // --------------------------------------------------------
    // GPIO
    // --------------------------------------------------------

    pinMode(
        RELAY_PIN,
        OUTPUT
    );

    pinMode(
        BUZZER_PIN,
        OUTPUT
    );

    pinMode(
        GREEN_LED_PIN,
        OUTPUT
    );

    pinMode(
        RED_LED_PIN,
        OUTPUT
    );

    // GPIO35 has NO internal pull-up.
    // External 10k pull-up to 3.3V is required.
    pinMode(
        EXIT_BUTTON_PIN,
        INPUT
    );

    digitalWrite(
        RELAY_PIN,
        LOW
    );

    digitalWrite(
        BUZZER_PIN,
        LOW
    );

    digitalWrite(
        GREEN_LED_PIN,
        LOW
    );

    digitalWrite(
        RED_LED_PIN,
        LOW
    );

    // --------------------------------------------------------
    // LittleFS
    // --------------------------------------------------------

    initFileSystem();

    // --------------------------------------------------------
    // NVS
    // --------------------------------------------------------

    preferences.begin(
        "access_system",
        false
    );

    readPointer =
        preferences.getUInt(
            "readPtr",
            0
        );

    writePointer =
        preferences.getUInt(
            "writePtr",
            0
        );

    globalSequence =
        preferences.getUInt(
            "seq",
            0
        );

    currentAclVersion =
        preferences.getUInt(
            "aclVer",
            0
        );

    if (
        readPointer >= MAX_EVENTS
    ) {
        readPointer = 0;
    }

    if (
        writePointer >= MAX_EVENTS
    ) {
        writePointer = 0;
    }

    // --------------------------------------------------------
    // ACL
    // --------------------------------------------------------

    loadAclToRAM();

    // --------------------------------------------------------
    // RTC
    // --------------------------------------------------------

    initRTC();

    // --------------------------------------------------------
    // RFID / HSPI
    // --------------------------------------------------------

    initRFID();

    // --------------------------------------------------------
    // Queue recovery
    // --------------------------------------------------------

    rebuildQueueState();

    // --------------------------------------------------------
    // Network task
    // --------------------------------------------------------

    xTaskCreatePinnedToCore(
        networkTaskCode,
        "NetworkTask",
        12000,
        nullptr,
        1,
        &NetworkTask,
        0
    );

    Serial.println(
        "Setup complete."
    );
}

// ============================================================
// 40. MAIN LOOP - CORE 1
// ============================================================

void loop() {

    // Completely non-blocking hardware handling.
    handleHardwareTimers();

    handleExitButton();

    handleRFID();

    // Yield without introducing a meaningful blocking delay.
    vTaskDelay(
        1 /
        portTICK_PERIOD_MS
    );
}