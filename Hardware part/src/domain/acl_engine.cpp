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

// RFID okuyucudan gelen her kart, buradan geçip GRANTED/UNKNOWN/EXPIRED/
// SCHEDULE sonuçlarından birine bağlanıyor. Kontroller kasıtlı olarak bu
// sırada: önce kart hiç tanınıyor mu (UNKNOWN), sonra süresi dolmuş mu
// (EXPIRED), sonra bu kat için yetkili mi, en son da zaman penceresi
// (SCHEDULE) - yani "kart hiç yok" ile "kart var ama şu an giremez"
// durumları backend'e/loglara farklı result kodlarıyla düşüyor, ikisi de
// aynı "UNKNOWN" içine gizlenmiyor (kat kontrolü hariç - bkz. aşağıdaki not).
uint8_t ACLEngine::evaluateAccess(const uint8_t* scannedUid, uint8_t uidLen, const DateTime& now) {
    AclRecord target = {};
    memcpy(target.uid, scannedUid, uidLen);
    target.uidLen = uidLen;

    uint8_t result = RESULT_UNKNOWN;

    // Mutex'i sonsuza kadar değil 100ms timeout ile bekliyoruz: bu fonksiyon
    // RFID okuma anında çağrılıyor ve kapı kilidi/buzzer bu sonuca bağlı -
    // ACL güncellemesi (processACLUpdate) aynı mutex'i tutarken bloklarsak
    // kullanıcı kartını okuttuğunda cihaz donmuş gibi görünmesin diye kısa
    // bir süre bekleyip pes ediyoruz (sonuç UNKNOWN'da kalır).
    if (xSemaphoreTake(aclMutex, pdMS_TO_TICKS(100)) == pdTRUE) {
        auto it = std::lower_bound(aclList.begin(), aclList.end(), target, compareAclRecords);
        
        // 1. UID Existence Check
        if (it == aclList.end() || target.uidLen != it->uidLen || memcmp(target.uid, it->uid, target.uidLen) != 0) {
            result = RESULT_UNKNOWN;

        // 2. Expiration Check
        } else if (now.unixtime() > it->valid_to) {
            result = RESULT_EXPIRED;

        // 3. Floor Bitmask Check
        // Not: burada da UNKNOWN dönüyoruz, EXPIRED gibi ayrı bir kod yok -
        // yani "kartın süresi dolmuş" ile "kart bu katta yetkili değil" dışarıdan
        // ayırt edilemiyor. Bilinçli mi yoksa gözden kaçmış mı emin değilim,
        // gerekirse ayrı bir result kodu (backend'deki MAP_RESULT'a da eklenerek) düşünülebilir.
        } else if ((it->floor_mask & (1UL << FLOOR_NUMBER)) == 0) {
            result = RESULT_UNKNOWN;

        // 4. Schedule Window Check (Cross-midnight & UTC-safe)
        // win_start_m/win_end_m gün içi dakika (0-1439). start<=end ise normal
        // aralık (örn. 08:00-19:00); start>end ise gece yarısını aşan bir
        // pencere demektir (örn. 22:00-06:00 gece vardiyası) - bu yüzden iki
        // ayrı karşılaştırma mantığı var.
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

    // Versiyon geriye gitmiyorsa veya aynıysa yok say - broadcast bir ACL
    // mesajı yeniden gelirse (retained MQTT mesajı, reconnect sonrası
    // tekrar subscribe vs.) flash'a gereksiz yazım yapılmasın diye.
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

    // Atomic file swap - önce yeni veriyi ayrı bir .tmp dosyasına yazdık,
    // şimdi eskiyi .bak'a taşıyıp .tmp'yi .bin yapıyoruz. Amaç: yazma
    // sırasında elektrik kesilirse (kapı okuyucularda bu gerçek bir risk)
    // yarım kalmış bir database.bin ile kalmamak - her adımda ya eski dosya
    // ya yeni dosya bütün halde duruyor. EventQueue::init() de açılışta
    // .bak'tan otomatik kurtarma yapıyor (bkz. o dosyadaki RECOVERY log'u).
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