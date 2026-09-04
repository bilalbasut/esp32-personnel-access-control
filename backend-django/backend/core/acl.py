"""
Binary ACL yayınlayıcısı - orijinal server.js'deki publishAclUpdate()'in
birebir portu.

Wire Format:
  Header (8 bytes):
    - ver:        uint32 LE (4 bytes)
    - card_count: uint32 LE (4 bytes)
  Records (20 bytes each):
    - uid:          7 bytes (raw hex bytes, padded with 0x00)
    - uidLen:       uint8   (1 byte)
    - floor_mask:   uint32 LE (4 bytes)
    - valid_to:     uint32 LE (4 bytes)
    - win_start_m:  uint16 LE (2 bytes)
    - win_end_m:    uint16 LE (2 bytes)
"""
import struct

from django.conf import settings
from django.db import connection

from core import mqtt_utils

def parse_floors(raw):
    """server.js'deki parseFloors()'un aynısı: '1,3' / [1,3] gibi girdileri int listesine normalize eder."""
    if raw is None:
        return []
    if isinstance(raw, (list, tuple)):
        out = []
        for v in raw:
            try:
                out.append(int(v))
            except (TypeError, ValueError):
                pass
        return out
    if isinstance(raw, str):
        out = []
        for part in raw.split(","):
            part = part.strip()
            if not part:
                continue
            try:
                out.append(int(part))
            except ValueError:
                pass
        return out
    return []

HEADER_SIZE = 8
RECORD_SIZE = 20

def _next_acl_version():
    with connection.cursor() as cursor:
        cursor.execute("SELECT nextval('acl_version_seq')")
        return cursor.fetchone()[0]


def build_acl_buffer(cards, version):
    card_count = len(cards)
    buf = bytearray(HEADER_SIZE + card_count * RECORD_SIZE)

    struct.pack_into("<II", buf, 0, version, card_count)

    offset = HEADER_SIZE
    for card in cards:
        normalized_uid = str(card.uid).strip().upper()
        try:
            uid_bytes = bytes.fromhex(normalized_uid)
        except ValueError:
            uid_bytes = b""
        uid_len = min(len(uid_bytes), 7)

        buf[offset:offset + uid_len] = uid_bytes[:uid_len]
        # 7'ye kadar kalan byte'lar zaten bytearray init'inden sıfır
        offset += 7

        struct.pack_into("<B", buf, offset, uid_len)
        offset += 1

        floor_mask = 0
        for f in parse_floors(card.floors):
            if 0 <= f < 32:
                floor_mask |= (1 << f)
        struct.pack_into("<I", buf, offset, floor_mask & 0xFFFFFFFF)
        offset += 4

        valid_to = int(card.valid_to) if card.valid_to is not None else 0xFFFFFFFF
        struct.pack_into("<I", buf, offset, valid_to & 0xFFFFFFFF)
        offset += 4

        local_start_m = card.win_start_m if card.win_start_m is not None else 0
        local_end_m = card.win_end_m if card.win_end_m is not None else 1440

        utc_start_m = local_start_m
        utc_end_m = local_end_m

        # Sadece tam gün erişim (0-1440) değilse çevir - server.js ile aynı.
        # Firmware her zaman UTC dakika bekliyor (bkz. acl_engine.cpp
        # evaluateAccess), pencereler burada local (Türkiye) saatle
        # girildiği için ikisi arasında fark var.
        if not (local_start_m == 0 and local_end_m == 1440):
            tz_offset_minutes = settings.TZ_OFFSET_MINUTES  # Türkiye = +180 dk

            utc_start_m = (local_start_m - tz_offset_minutes) % 1440
            if utc_start_m < 0:
                utc_start_m += 1440

            utc_end_m = (local_end_m - tz_offset_minutes) % 1440
            if utc_end_m < 0:
                utc_end_m += 1440

        struct.pack_into("<H", buf, offset, utc_start_m)
        offset += 2
        struct.pack_into("<H", buf, offset, utc_end_m)
        offset += 2

    return bytes(buf)


def publish_acl_update():
    """Aktif kartlardan binary ACL'i yeniden kurar ve server.js'deki
    publishAclUpdate() ile birebir aynı şekilde pdks/merkez/cfg/acl'e
    retained olarak yayınlar."""
    from cards.models import Card
    cards = list(
        Card.objects.filter(is_active=True).values_list(
            "uid", "floors", "valid_to", "win_start_m", "win_end_m", named=True
        )
    )
    version = _next_acl_version()
    buf = build_acl_buffer(cards, version)

    mqtt_utils.publish("pdks/merkez/cfg/acl", buf, qos=1, retain=True)
    return version, len(cards), len(buf)
