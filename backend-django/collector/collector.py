"""
collector.js'in paho-mqtt + psycopg2 kullanan birebir portu. Aynı topic'lere
subscribe olur, aynı string->SMALLINT çeviri tablolarını ve zaman damgası
mantık kontrolünü uygular, aynı tablolara yazar.
"""
import json
import os
import time

import paho.mqtt.client as mqtt
import psycopg2

import db

MQTT_HOST = os.environ.get("MQTT_HOST", "127.0.0.1")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))

# --- ÇEVİRİ TABLOLARI ---
# ESP32'nin string payload'larını PostgreSQL için SMALLINT'e çevirir
MAP_RESULT = {"granted": 0, "unknown": 1, "expired": 2, "schedule": 3, "manual": 4}
MAP_DIR = {"in": 0, "out": 1}
MAP_MODE = {"online": 0, "offline": 1}
MAP_TSRC = {"ntp": 0, "rtc": 1, "invalid": 2}

conn = db.connect()  # returns an autocommit connection - see db.py
db.wait_for_schema(conn)


def now_s():
    return int(time.time())


def send_ack(client, device_id, seq_number):
    ack_topic = f"pdks/merkez/dev/{device_id}/event/ack"
    ack_payload = json.dumps({"ack_seq": seq_number})
    try:
        client.publish(ack_topic, ack_payload, qos=1)
    except Exception as err:
        print(f"Failed to send ACK: {err}", flush=True)


def handle_event(client, device_id, payload):
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        print("Invalid JSON payload", flush=True)
        return

    now = now_s()

    # "fw" sadece event payload'larında görünür (heartbeat'te değil), burası tek yakalama noktası.
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO devices (id, status, last_seen_at, fw, created_at, updated_at)
                VALUES (%s, 'online', %s, %s, NOW(), NOW())
                ON CONFLICT(id) DO UPDATE SET status = 'online', last_seen_at = EXCLUDED.last_seen_at, fw = EXCLUDED.fw, updated_at = NOW()
                """,
                (device_id, now, data.get("fw") or None),
            )
    except Exception as err:
        print(f"Device fw/presence update error: {err}", flush=True)

    # String'leri integer'a çevir (tanımsızsa güvenli değerlere düş)
    res_int = MAP_RESULT.get(data.get("res"), 1)   # Varsayılan: 1 (unknown)
    dir_int = MAP_DIR.get(data.get("dir"), 0)      # Varsayılan: 0 (in)
    mode_int = MAP_MODE.get(data.get("mode"), 0)   # Varsayılan: 0 (online)
    tsrc_int = MAP_TSRC.get(data.get("tsrc"), 2)   # Varsayılan: 2 (invalid)

    ts = data.get("ts")
    # Mantık kontrolü: zaman damgası gelecekte ise (>10 dk) ya da 2025'ten önceyse geçersiz say
    if ts is None or ts > (now + 600) or ts < 1735689600:
        print(f"[TIMESTAMP ANOMALY] Device {device_id} sent suspect ts: {ts}. Overriding tsrc to invalid.", flush=True)
        tsrc_int = 2  # TSRC_INVALID

    # Bu UID'ye bağlı employee_id'yi bul
    employee_id = None
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT employee_id FROM cards WHERE uid = %s", (data.get("uid"),))
            row = cur.fetchone()
            if row:
                employee_id = row[0]
    except Exception as err:
        print(f"Error looking up employee ID: {err}", flush=True)

    query = """
        INSERT INTO access_events
        (device_id, seq, uid, employee_id, ts_utc, ts_source, dir, result, mode, ingested_at, raw_payload)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
    """
    values = (  # raw_payload replay/backfill için saklanır, eşleme hatası veri kaybettirmesin diye
        device_id, data.get("seq"), data.get("uid"), employee_id, ts, tsrc_int, dir_int, res_int, mode_int, now,
        json.dumps(data),
    )

    try:
        with conn.cursor() as cur:
            cur.execute(query, values)
        print(f"Record saved. Sending ACK for Seq: {data.get('seq')}", flush=True)
        send_ack(client, device_id, data.get("seq"))
    except psycopg2.errors.UniqueViolation:
        conn.rollback()
        print(f"Duplicate record ignored (Device: {device_id}, Seq: {data.get('seq')})", flush=True)
        send_ack(client, device_id, data.get("seq"))
    except Exception as err:
        conn.rollback()
        print(f"Database insertion error: {err}", flush=True)


def handle_status(device_id, payload):
    now = now_s()
    query = """
        INSERT INTO devices (id, status, last_seen_at, created_at, updated_at)
        VALUES (%s, %s, %s, NOW(), NOW())
        ON CONFLICT(id) DO UPDATE SET status = EXCLUDED.status, last_seen_at = EXCLUDED.last_seen_at, updated_at = NOW()
    """
    try:
        with conn.cursor() as cur:
            cur.execute(query, (device_id, payload, now))
        print(f"Device {device_id} status: {payload}", flush=True)
    except Exception as err:
        conn.rollback()
        print(f"Device status update error: {err}", flush=True)


def handle_heartbeat(device_id, payload):
    now = now_s()
    try:
        hb = json.loads(payload)
    except json.JSONDecodeError:
        hb = {}
        print("Invalid heartbeat JSON, storing presence only.", flush=True)

    # upsert, kör UPDATE değil - ilk /status'tan önce gelen heartbeat veri kaybettirmesin
    query = """
        INSERT INTO devices (id, status, last_seen_at, queue_depth, heap_free, queue_overflow, uptime_s, created_at, updated_at)
        VALUES (%s, 'online', %s, %s, %s, %s, %s, NOW(), NOW())
        ON CONFLICT(id) DO UPDATE SET
            status = 'online',
            last_seen_at = EXCLUDED.last_seen_at,
            queue_depth = EXCLUDED.queue_depth,
            heap_free = EXCLUDED.heap_free,
            queue_overflow = EXCLUDED.queue_overflow,
            uptime_s = EXCLUDED.uptime_s,
            updated_at = NOW()
    """
    try:
        with conn.cursor() as cur:
            cur.execute(
                query,
                (
                    device_id, now,
                    hb.get("queue"), hb.get("heap"), hb.get("qOverflow"), hb.get("uptime"),
                ),
            )
    except Exception as err:
        conn.rollback()
        print(f"Heartbeat update error: {err}", flush=True)


def handle_cmd_res(device_id, payload):
    print(f"[CMD RESULT] Device {device_id} responded: {payload}", flush=True)

    # Sadece OTA yanıtları kalıcı saklanır (panel ilerleme göstersin diye), diğerleri geçici ack.
    if payload.startswith("ota_"):
        now = now_s()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO devices (id, status, last_seen_at, ota_status, ota_updated_at, created_at, updated_at)
                    VALUES (%s, 'online', %s, %s, %s, NOW(), NOW())
                    ON CONFLICT(id) DO UPDATE SET
                        status = 'online',
                        last_seen_at = EXCLUDED.last_seen_at,
                        ota_status = EXCLUDED.ota_status,
                        ota_updated_at = EXCLUDED.ota_updated_at,
                        updated_at = NOW()
                    """,
                    (device_id, now, payload, now),
                )
        except Exception as err:
            conn.rollback()
            print(f"OTA status update error: {err}", flush=True)


def on_connect(client, userdata, flags, rc):
    print("Collector connected to Mosquitto MQTT Broker", flush=True)
    client.subscribe("pdks/merkez/dev/+/event", qos=1)
    client.subscribe("pdks/merkez/dev/+/status", qos=1)
    client.subscribe("pdks/merkez/dev/+/hb", qos=0)
    client.subscribe("pdks/merkez/dev/+/cmd/res", qos=1)


def on_disconnect(client, userdata, rc):
    print(f"MQTT connection error/disconnected: rc={rc}", flush=True)


def on_message(client, userdata, msg):
    topic = msg.topic
    payload = msg.payload.decode("utf-8", errors="replace")
    topic_parts = topic.split("/")
    device_id = topic_parts[3] if len(topic_parts) > 3 else None

    if topic.endswith("/event"):
        handle_event(client, device_id, payload)
    elif topic.endswith("/status"):
        handle_status(device_id, payload)
    elif topic.endswith("/hb"):
        handle_heartbeat(device_id, payload)
    elif topic.endswith("/cmd/res"):
        handle_cmd_res(device_id, payload)


def main():
    client = mqtt.Client()
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = on_message

    while True:
        try:
            client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
            client.loop_forever()
        except Exception as err:
            print(f"MQTT connection error: {err}", flush=True)
            time.sleep(3)


if __name__ == "__main__":
    main()
