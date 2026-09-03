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

// mqttCallback() ARTIK mqtt.publish()/mqtt.subscribe() çağırmıyor - onun yerine
// burada kuyruğa yazıyor, gerçek gönderim mqtt.loop() döngüden tamamen
// döndükten SONRA (taskLoop içinde) yapılıyor. Sebep: 256dpi/arduino-mqtt
// kütüphanesinin kendi README'si callback içeriden publish/subscribe/unsubscribe
// çağrılmasını AÇIKÇA yasaklıyor ("may cause deadlocks when other things
// arrive while sending and receiving acknowledgments"). Bunu görmezden
// gelmek üretimde görülen "GATE-K3-01 online/offline flap + aynı OTA
// komutu (seq) sonsuz tekrar" sorununun kök nedeniydi: callback içinde
// publish etmek MQTT bağlantı durumunu bozup broker'ın bağlantıyı
// kesmesine yol açıyordu (LWT -> "offline"); setOptions() ile clean
// session=false olduğundan (bkz. initMQTT), broker henüz PUBACK
// alamadığı QoS1 komutu her reconnect'te tekrar tekrar gönderiyordu -
// cihaz duplicate'i reddedip tekrar publish edince döngü kendini
// besliyordu. 3 slotluk kuyruk, OTA gibi tek bir komutun iki ayrı
// cevap üretebildiği (örn. "ota_downloading" sonra "ota_ok_rebooting")
// durumları kaybetmemek için var.
static const uint8_t CMD_RES_QUEUE_LEN = 3;
static char pendingCmdResQueue[CMD_RES_QUEUE_LEN][32];
static volatile uint8_t pendingCmdResCount = 0;
static volatile bool pendingAclResubscribe = false;

static void queueCmdRes(const char* msg) {
    if (pendingCmdResCount >= CMD_RES_QUEUE_LEN) return; // taşarsa fazlasını sessizce düşür
    strncpy(pendingCmdResQueue[pendingCmdResCount], msg, sizeof(pendingCmdResQueue[0]) - 1);
    pendingCmdResQueue[pendingCmdResCount][sizeof(pendingCmdResQueue[0]) - 1] = '\0';
    pendingCmdResCount++;
}

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
                queueCmdRes("cmd_failed_bad_json");
                return;
            }

            uint32_t seq = cmdDoc["seq"] | 0UL;
            const char* subCmd = cmdDoc["cmd"] | "";
            uint32_t cmdTs = cmdDoc["ts"] | 0UL;

            // MQTT QoS1 aynı mesajı birden fazla teslim edebilir - seq ile
            // "bu komutu zaten işledik" tekrarlarını eleyip aynı "open"/
            // "reboot" komutunun iki kez uygulanmasını önlüyoruz.
            if (seq <= lastCmdSeq && seq != 0) {
                Serial.printf("Duplicate command seq=%u ignored.\n", seq);
                queueCmdRes("cmd_duplicate_ignored");
                return;
            }

            // Komut 15 saniyeden daha eski gönderilmişse (ağ gecikmesi, broker
            // tarafında bekleyen retained mesaj vb.) uygulanmıyor - özellikle
            // "open" gibi komutların çok sonra gelip beklenmedik anda kapıyı
            // açması istenmiyor. RTC zaten güvenilmezse (TSRC_INVALID) bu
            // kontrol tamamen atlanıyor, çünkü now.unixtime() kendisi şüpheli.
            DateTime now = RTCService::rtcNowSafe();
            if (RTCService::currentTimeSource != TSRC_INVALID && cmdTs > 0) {
                if (now.unixtime() > (cmdTs + 15)) {
                    Serial.printf("Expired command '%s' discarded.\n", subCmd);
                    queueCmdRes("cmd_expired_discarded");
                    lastCmdSeq = seq;
                    return;
                }
            }

            lastCmdSeq = seq;

            if (strcmp(subCmd, "open") == 0) {
                static const uint8_t remoteUid[7] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};
                bool logged = EventQueue::logAccess(now, remoteUid, 7, DIR_IN, RESULT_MANUAL);
                IOController::grantAccess();
                queueCmdRes(logged ? "open_ok" : "open_ok_unlogged");
                if (!logged) Serial.println("WARNING: Remote open succeeded but event logging failed.");

            } else if (strcmp(subCmd, "reboot") == 0) {
                queueCmdRes("rebooting");
                rebootPending = true;
                rebootRequestedAt = millis();

            } else if (strcmp(subCmd, "sync") == 0) {
                ACLEngine::resetVersion();
                pendingAclResubscribe = true;
                queueCmdRes("sync_triggered");

            } else if (strcmp(subCmd, "settime") == 0) {
                uint32_t newTs = cmdDoc["ts"] | 0UL;
                if (newTs >= 1735689600UL && newTs <= 2051222400UL) {
                    RTCService::rtcAdjustSafe(DateTime(newTs));
                    RTCService::currentTimeSource = TSRC_RTC;
                    RTCService::lastNtpSync = millis();
                    queueCmdRes("settime_ok");
                    Serial.printf("RTC time updated via backend command to: %lu\n", newTs);
                } else {
                    queueCmdRes("settime_failed_invalid_ts");
                }

            } else if (strcmp(subCmd, "ota") == 0) {
                String otaUrl = cmdDoc["url"] | "";
                String otaMd5 = cmdDoc["md5"] | "";
                uint32_t otaSize = cmdDoc["size"] | 0UL;

                if (otaUrl.length() == 0 || otaMd5.length() != 32) {
                    queueCmdRes("ota_failed_bad_request");
                    return;
                }

                // NOT: "ota_downloading" burada kuyruğa giriyor ama gerçekten
                // gönderilmesi - kuyruk sadece mqtt.loop() döndükten sonra
                // boşaltıldığı için - performOTA() (aşağıda, bloklayan bir HTTP
                // indirmesi) bitene kadar ERTELENİYOR; yani panel artık indirme
                // SIRASINDA "downloading" durumunu gerçek zamanlı göremiyor,
                // indirme bitince "downloading" ve final sonuç (ok/failed) art
                // arda gelecek. Bu, publish-in-callback bug'ını çözmenin kabul
                // edilen bir yan etkisi - gerçek zamanlı ara durum istenirse
                // OTA tetiklemesinin tamamen ana loop'a taşınması gerekir
                // (reboot'ta olduğu gibi bir pendingOta bayrağıyla) - şimdilik
                // kapsam dışı bırakıldı.
                queueCmdRes("ota_downloading");
                bool ok = OTAUpdater::performOTA(otaUrl, otaMd5, otaSize);

                if (ok) {
                    queueCmdRes("ota_ok_rebooting");
                    rebootPending = true;
                    rebootRequestedAt = millis();
                } else {
                    queueCmdRes("ota_failed");
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

// --- Store-and-forward: basit "stop-and-wait" mantığı ---
// EventQueue'daki en eski (henüz backend'e ulaşmamış) kayıt tek tek
// publishQueueHead() ile gönderilir; collector.py bunu işleyip ack_seq
// döndürene kadar (processPendingAck) kuyruktan bir sonrakine geçilmez.
// MQTT'nin kendi QoS1 ack'i sadece broker'a ulaştığını garanti eder,
// collector'ın DB'ye yazdığını değil - asıl "kabul edildi" sinyali bu
// uygulama seviyesindeki ack_seq mesajı. Ack gelmezse ACK_TIMEOUT_MS sonra
// pes edilip aynı kayıt tekrar denenir (collector tarafı zaten
// device_id+seq üzerinde UNIQUE constraint ile tekrarları güvenle yutuyor).
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
            static uint8_t lastObservedTimeSource = TSRC_INVALID;

            // Zaman kaynağı bu turda İLK KEZ "şüpheli"ye (TSRC_INVALID) düştüyse
            // - rtcNowSafe() bir bozulma/mantıksız sıçrama tespit ettiği için -
            // bir sonraki NTP denemesini zorla hemen tetikle. lastNtpAttempt=0
            // yapmak, saatlik senkron periyodunun ortasında olsak bile (henüz
            // birkaç saniye önce başarılı bir NTP denemesi yapılmış olsa dahi)
            // bekleme kalıntısını sıfırlar - "şüpheli" durumda saatlerce yanlış
            // zamanla event üretmeye devam etmek yerine anında düzeltme denenir.
            uint8_t currentSourceNow = RTCService::currentTimeSource;
            if (currentSourceNow == TSRC_INVALID && lastObservedTimeSource != TSRC_INVALID) {
                lastNtpAttempt = 0;
                Serial.println("WARNING: Time source became suspected (TSRC_INVALID) - forcing immediate NTP retry.");
            }
            lastObservedTimeSource = currentSourceNow;

            // Zaten NTP ile senkronsa saatte bir yeniden dener (NTP_SYNC_INTERVAL_MS);
            // senkron değilse (henüz hiç senkron olamadı YA DA az önce şüpheli
            // işaretlendi) her 15 saniyede bir dener - cihaz gerçek zamana mümkün
            // olduğunca hızlı kavuşsun, RTC dead-reckoning'e bel bağlama süresi kısalsın.
            unsigned long ntpInterval = (currentSourceNow == TSRC_NTP) ? NTP_SYNC_INTERVAL_MS : 15000UL;

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
                        // Exponential backoff + jitter: broker yeniden başladığında
                        // sahadaki tüm cihazlar aynı anda değil, saçılarak
                        // reconnect denesin diye (random jitter olmasaydı hepsi
                        // aynı milisaniyede tekrar deneyip broker'ı boğardı).
                        backoff = min(backoff * 2, 60000UL);
                        backoff += random(0, 1000);
                    }
                    lastReconnectAttempt = now;
                }
            } else {
                mqtt.loop();

                // mqttCallback() sırasında kuyruğa yazılan cevaplar/aboneliği
                // burada, mqtt.loop() çağrısı TAMAMEN bittikten sonra gönderilir
                // - neden için bkz. pendingCmdResQueue tanımının yanındaki not.
                for (uint8_t i = 0; i < pendingCmdResCount; i++) {
                    mqtt.publish(TOPIC_CMD_RES, pendingCmdResQueue[i], false, 1);
                }
                pendingCmdResCount = 0;
                if (pendingAclResubscribe) {
                    pendingAclResubscribe = false;
                    mqtt.subscribe(TOPIC_ACL, 1);
                }

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
            // Ethernet linki yokken NTP güveni de düşer, ama bu satır bilerek
            // SADECE TSRC_NTP -> TSRC_RTC indirgemesi yapıyor. Eskiden burada
            // koşulsuzca TSRC_RTC yazılıyordu - bu, rtcNowSafe()'in az önce
            // tespit ettiği TSRC_INVALID (şüpheli/bozuk zaman) bayrağını link
            // sadece düştü diye sessizce "güvenilir"e çeviriyordu. Kötü bir
            // zamanı iyiymiş gibi göstermek, iyi bir zamanı güvensiz göstermekten
            // çok daha tehlikeli - bu yüzden INVALID durumuna hiç dokunmuyoruz;
            // düzeltmeyi yine NTP (link geri geldiğinde) ya da settime komutu yapsın.
            if (RTCService::currentTimeSource == TSRC_NTP) {
                RTCService::currentTimeSource = TSRC_RTC;
            }
        }

        EventQueue::saveCheckpoint(false);
        vTaskDelay(25 / portTICK_PERIOD_MS);
    }
}