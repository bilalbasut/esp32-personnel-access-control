#include "network_manager.h"
#include <SPI.h>
#include <Ethernet.h>
#include <EthernetUdp.h>
#include <NTPClient.h>
#include <MQTT.h>
#include <ArduinoJson.h>
#include <esp_task_wdt.h>
#include <vector>
#include "config.h"
#include "types.h"
#include "ota_updater.h"
#include "ota_guard.h"
#include "../hal/rtc_service.h"
#include "../hal/io_controller.h"
#include "../storage/event_queue.h"
#include "../domain/acl_engine.h"

static EthernetUDP ntpUDP;
static NTPClient timeClient(ntpUDP, "pool.ntp.org", 0, 60000);
static EthernetClient ethClient;
static MQTTClient mqtt(16384); // 16KB buffer for large ACL messages

static volatile bool rebootPending = false;
static unsigned long rebootRequestedAt = 0;
static uint32_t lastCmdSeq = 0;

static volatile bool ackReceived = false;
static volatile uint32_t pendingAckSeq = 0;
static volatile bool aclMessageReceived = false;
static std::vector<uint8_t> pendingAclBytes;

bool NetworkManager::isMqttConnected() {
    return mqtt.connected();
}

static void initEthernet() {
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

static void mqttCallback(MQTTClient *client, char topic[], char bytes[], int length) {
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

            DateTime now = RTCService::rtcNowSafe();
            if (RTCService::currentTimeSource != TSRC_INVALID && cmdTs > 0) {
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
                bool logged = EventQueue::logAccess(now, remoteUid, 7, DIR_IN, RESULT_MANUAL);
                IOController::grantAccess();
                mqtt.publish(TOPIC_CMD_RES, logged ? "open_ok" : "open_ok_unlogged", false, 1);
                if (!logged) Serial.println("WARNING: Remote open succeeded but event logging failed.");

            } else if (strcmp(subCmd, "reboot") == 0) {
                mqtt.publish(TOPIC_CMD_RES, "rebooting", false, 1);
                rebootPending = true;
                rebootRequestedAt = millis();

            } else if (strcmp(subCmd, "sync") == 0) {
                ACLEngine::resetVersion();
                mqtt.subscribe(TOPIC_ACL, 1);
                mqtt.publish(TOPIC_CMD_RES, "sync_triggered", false, 1);

            } else if (strcmp(subCmd, "settime") == 0) {
                uint32_t newTs = cmdDoc["ts"] | 0UL;
                if (newTs >= 1735689600UL && newTs <= 2051222400UL) {
                    RTCService::rtcAdjustSafe(DateTime(newTs));
                    RTCService::currentTimeSource = TSRC_RTC;
                    RTCService::lastNtpSync = millis();
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
                bool ok = OTAUpdater::performOTA(otaUrl, otaMd5, otaSize);

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

static void initMQTT() {
    mqtt.begin(mqttServer, MQTT_PORT, ethClient);
    mqtt.setOptions(30, false, 1000);
    mqtt.onMessageAdvanced(mqttCallback);
    mqtt.setWill(TOPIC_STATUS, "offline", true, 1);
}

static bool processPendingAck(bool currentlyWaiting) {
    if (!currentlyWaiting || !ackReceived) return currentlyWaiting;
    ackReceived = false;

    if (EventQueue::queueIsEmpty()) return false;
    AccessRecord record;
    if (!EventQueue::readEventRecord(EventQueue::getReadPointer(), record) || !isRecordValid(record)) return currentlyWaiting;

    if (record.seq == pendingAckSeq) {
        EventQueue::advanceReadPointer();
        Serial.printf("ACK accepted seq=%d\n", pendingAckSeq);
        return false;
    }
    return currentlyWaiting;
}

static bool buildEventPayload(const AccessRecord& record, char* buffer, size_t bufferSize) {
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

static bool publishQueueHead() {
    if (!mqtt.connected() || EventQueue::queueIsEmpty()) return false;
    AccessRecord record;
    if (!EventQueue::readEventRecord(EventQueue::getReadPointer(), record) || !isRecordValid(record)) return false;

    char payload[384];
    if (!buildEventPayload(record, payload, sizeof(payload))) return false;

    bool published = mqtt.publish(TOPIC_EVENT, payload, false, 1);
    if (published) Serial.printf("QoS1 publish seq=%d\n", record.seq);
    return published;
}

void NetworkManager::taskLoop(void* parameter) {
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
            unsigned long ntpInterval = (RTCService::currentTimeSource == TSRC_NTP) ? NTP_SYNC_INTERVAL_MS : 15000UL;

            if (lastNtpAttempt == 0 || now - lastNtpAttempt >= ntpInterval) {
                lastNtpAttempt = now;
                
                if (timeClient.forceUpdate()) {
                    unsigned long epoch = timeClient.getEpochTime();
                    
                    if (epoch >= 1735689600UL && epoch <= 2051222400UL) {
                        RTCService::rtcAdjustSafe(DateTime(epoch));
                        RTCService::currentTimeSource = TSRC_NTP;
                        RTCService::lastNtpSync = now;
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
                        OtaGuard::confirmHealth();
                    } else {
                        backoff = min(backoff * 2, 60000UL);
                        backoff += random(0, 1000);
                    }
                    lastReconnectAttempt = now;
                }
            } else {
                mqtt.loop();
                waitingForAck = processPendingAck(waitingForAck);
                
                if (aclMessageReceived) {
                    aclMessageReceived = false;
                    ACLEngine::processACLUpdate(pendingAclBytes);
                }

                // Heartbeat
                if (now - lastHeartbeat >= HEARTBEAT_INTERVAL_MS) {
                    JsonDocument hb;
                    hb["uptime"] = millis() / 1000; 
                    hb["queue"] = EventQueue::getQueueCount(); 
                    hb["heap"] = ESP.getFreeHeap(); 
                    hb["rssi"] = 0;
                    hb["qOverflow"] = EventQueue::getQueueOverflowCount();

                    char hbPayload[128];
                    serializeJson(hb, hbPayload, sizeof(hbPayload));
                    mqtt.publish(TOPIC_HEARTBEAT, hbPayload, false, 0);
                    lastHeartbeat = now;
                }

                // Store-and-forward Processing
                if (!EventQueue::queueIsEmpty()) {
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
            RTCService::currentTimeSource = TSRC_RTC;
        }

        EventQueue::saveCheckpoint(false);
        vTaskDelay(25 / portTICK_PERIOD_MS);
    }
}