#include "rfid_reader.h"
#include <SPI.h>
#include <MFRC522v2.h>
#include <MFRC522DriverSPI.h>
#include <MFRC522DriverPinSimple.h>
#include "config.h"
#include "types.h"
#include "rtc_service.h"
#include "io_controller.h"
#include "../domain/acl_engine.h"
#include "../storage/event_queue.h"

static SPIClass hspi(HSPI);
static MFRC522DriverPinSimple rfidSS(RFID_SS_PIN);
static MFRC522DriverSPI rfidDriver(rfidSS, hspi);
static MFRC522 rfid(rfidDriver);

static uint8_t lastUid[7] = {0};
static uint8_t lastUidLen = 0;
static unsigned long lastScanTime = 0;

void RFIDReader::init() {
    hspi.begin(RFID_SCK_PIN, RFID_MISO_PIN, RFID_MOSI_PIN, RFID_SS_PIN);
    rfid.PCD_Init();
    delay(10);
    Serial.printf("MFRC522 firmware: 0x%02X\n", rfid.PCD_GetVersion());
}

void RFIDReader::update() {
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

    DateTime now = RTCService::rtcNowSafe();
    uint8_t resultCode = ACLEngine::evaluateAccess(uidBytes, uidLen, now);

    if (EventQueue::logAccess(now, uidBytes, uidLen, DEVICE_DIR, resultCode)) {
        if (resultCode == RESULT_GRANTED) {
            IOController::grantAccess();
        } else {
            IOController::denyAccess();
        }
    } else {
        IOController::denyAccess();
        Serial.println("SYSTEM ERROR: User denied due to logging failure.");
    }
}