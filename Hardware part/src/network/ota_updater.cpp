#include "ota_updater.h"
#include <Ethernet.h>
#include <Update.h>
#include <esp_task_wdt.h>
#include "config.h"

static bool parseHttpUrl(const String& url, String& host, uint16_t& port, String& path) {
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

bool OTAUpdater::performOTA(const String& url, const String& expectedMd5, uint32_t expectedSize) {
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

    // Ethernet kütüphanesinde hazır bir HTTP client yok, bu yüzden GET isteği
    // ve header parse'ı burada elle yapılıyor: status satırını oku, header'ları
    // boş satıra kadar oku (sadece Content-Length ile ilgileniyoruz), sonrasını
    // ham byte akışı olarak Update.write()'a stream ediyoruz.
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

        // İki ayrı zaman aşımı var: OTA_STALL_TIMEOUT_MS "veri akışı durdu mu"
        // (aşağıda lastDataMs ile), OTA_TOTAL_TIMEOUT_MS ise "indirme bir
        // türlü bitmiyor" (yavaş ama kesintisiz bir bağlantı da sonsuza kadar
        // sürmesin diye) - ikisi farklı arıza türlerini yakalıyor.
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