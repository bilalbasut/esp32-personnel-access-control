#include "acl_engine.h"
#include <LittleFS.h>
#include <Preferences.h>
#include <algorithm>
#include "config.h"

static SemaphoreHandle_t aclMutex = NULL;
static std::vector<AclRecord> aclList;
static uint32_t currentAclVersion = 0;
static Preferences aclPreferences;

void ACLEngine::init() {
    aclMutex = xSemaphoreCreateMutex();
    aclPreferences.begin("access_system", false);
    currentAclVersion = aclPreferences.getUInt("aclVer", 0);
    loadAclToRAM();
}

uint32_t ACLEngine::getCurrentVersion() {
    return currentAclVersion;
}

void ACLEngine::resetVersion() {
    currentAclVersion = 0;
    aclPreferences.putUInt("aclVer", 0);
}

void ACLEngine::loadAclToRAM() {
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

uint8_t ACLEngine::evaluateAccess(const uint8_t* scannedUid, uint8_t uidLen, const DateTime& now) {
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

void ACLEngine::processACLUpdate(std::vector<uint8_t>& pendingBytes) {
    if (pendingBytes.size() < sizeof(AclHeader)) {
        pendingBytes.clear();
        return;
    }

    AclHeader* hdr = reinterpret_cast<AclHeader*>(pendingBytes.data());
    uint32_t newVersion = hdr->ver;
    uint32_t cardCount = hdr->count;

    size_t expectedSize = sizeof(AclHeader) + (cardCount * sizeof(AclRecord));
    if (pendingBytes.size() != expectedSize) {
        Serial.printf("ERROR: Binary ACL size mismatch (got %u, expected %u)\n", 
                      pendingBytes.size(), expectedSize);
        pendingBytes.clear();
        return;
    }

    if (newVersion <= currentAclVersion) {
        pendingBytes.clear();
        return;
    }

    File dbFile = LittleFS.open("/database.tmp", FILE_WRITE);
    if (!dbFile) {
        Serial.println("ERROR: Cannot open /database.tmp for writing.");
        pendingBytes.clear();
        return;
    }

    // Write all records directly to flash in one contiguous operation
    const uint8_t* recordsPtr = pendingBytes.data() + sizeof(AclHeader);
    size_t bytesToWrite = cardCount * sizeof(AclRecord);

    if (bytesToWrite > 0) {
        dbFile.write(recordsPtr, bytesToWrite);
    }
    dbFile.flush();
    dbFile.close();

    // Free reception buffer immediately
    pendingBytes.clear();
    pendingBytes.shrink_to_fit();

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
    aclPreferences.putUInt("aclVer", currentAclVersion);
    Serial.printf("Binary ACL updated: ver=%u, cards=%u (%u bytes)\n", 
                  currentAclVersion, cardCount, bytesToWrite);
}