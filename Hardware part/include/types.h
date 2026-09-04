#pragma once
#include <Arduino.h>
#include <cstring>

// ============================================================
// 2. DATA STRUCTURES & ENUMS
// ============================================================
// /events.bin'e byte byte yazılan sabit disk formatı - alan ekleme/çıkarma/sıra
// değişikliği flash'taki eski kayıtları bozar. `reserved[9]` ileride migration'sız genişleme payı.
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

static_assert(sizeof(AccessRecord) == 32, "AccessRecord must be 32 bytes");

enum Direction : uint8_t { DIR_IN = 0, DIR_OUT = 1 };
enum ResultCode : uint8_t { RESULT_GRANTED = 0, RESULT_UNKNOWN = 1, RESULT_EXPIRED = 2, RESULT_SCHEDULE = 3, RESULT_MANUAL = 4 };
enum TimeSource : uint8_t { TSRC_NTP = 0, TSRC_RTC = 1, TSRC_INVALID = 2 };

// CRC16 - güç kesintisiyle yarım kalan yazımları isRecordValid() ile tespit edip eleme.
inline uint16_t calculateCRC16(const uint8_t* data, size_t length) {
    uint16_t crc = 0xFFFF;
    for (size_t i = 0; i < length; i++) {
        crc ^= data[i];
        for (uint8_t bit = 0; bit < 8; bit++) crc = (crc & 0x0001) ? (crc >> 1) ^ 0xA001 : (crc >> 1);
    }
    return crc;
}

inline uint16_t calculateRecordCRC(const AccessRecord& record) {
    return calculateCRC16(reinterpret_cast<const uint8_t*>(&record), sizeof(AccessRecord) - sizeof(record.crc16));
}

inline bool isRecordValid(const AccessRecord& record) {
    if (record.seq == 0 || record.uidLen > 7) return false;
    return calculateRecordCRC(record) == record.crc16;
}

inline uint8_t hexNibble(char c) {
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    return 0;
}

inline bool isValidHex(const char* hex, size_t len) {
    if (len == 0 || len % 2 != 0 || len > 14) return false;
    for (size_t i = 0; i < len; i++) {
        char c = hex[i];
        if (!((c >= '0' && c <= '9') || (c >= 'A' && c <= 'F') || (c >= 'a' && c <= 'f'))) {
            return false;
        }
    }
    return true;
}

inline void hexToBytes(const char* hex, size_t hexLen, uint8_t* byteArray, uint8_t maxLen) {
    memset(byteArray, 0, maxLen);
    for (size_t i = 0; i + 1 < hexLen && (i / 2) < maxLen; i += 2) {
        byteArray[i / 2] = (hexNibble(hex[i]) << 4) | hexNibble(hex[i + 1]);
    }
}

inline void bytesToHex(const uint8_t* bytes, uint8_t len, char* out, size_t outSize) {
    static const char hexChars[] = "0123456789ABCDEF";
    size_t pos = 0;
    for (uint8_t i = 0; i < len && pos + 2 < outSize; i++) {
        out[pos++] = hexChars[bytes[i] >> 4];
        out[pos++] = hexChars[bytes[i] & 0x0F];
    }
    out[pos] = '\0';
}

inline const char* resultToText(uint8_t result) {
    switch (result) {
        case RESULT_GRANTED: return "granted";
        case RESULT_UNKNOWN: return "unknown";
        case RESULT_EXPIRED: return "expired";
        case RESULT_SCHEDULE: return "schedule";
        case RESULT_MANUAL: return "manual";
        default: return "unknown";
    }
}
inline const char* directionToText(uint8_t direction) { return direction == DIR_OUT ? "out" : "in"; }
inline const char* modeToText(uint8_t mode) { return mode == 0 ? "online" : "offline"; }
inline const char* timeSourceToText(uint8_t source) {
    switch (source) { case TSRC_NTP: return "ntp"; case TSRC_RTC: return "rtc"; default: return "invalid"; }
}

// evaluateAccess()'in std::lower_bound araması için liste hep bu sırada kalmalı (loadAclToRAM()'daki sort da aynısını kullanır).
inline bool compareAclRecords(const AclRecord& a, const AclRecord& b) {
    if (a.uidLen != b.uidLen) return a.uidLen < b.uidLen;
    return memcmp(a.uid, b.uid, a.uidLen) < 0;
}