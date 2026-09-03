"""
Direct port of collector.js using paho-mqtt + psycopg2. Subscribes to the
same topics, applies the same string->SMALLINT translation maps and
timestamp sanity check, and writes to the same tables.
"""
import json
import os
import time

import paho.mqtt.client as mqtt
import psycopg2

import db

MQTT_HOST = os.environ.get("MQTT_HOST", "127.0.0.1")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))

# --- TRANSLATION MAPS ---
# Converts ESP32 string payloads back into SMALLINT for PostgreSQL
MAP_RESULT = {"granted": 0, "unknown": 1, "expired": 2, "schedule": 3, "manual": 4}
MAP_DIR = {"in": 0, "out": 1}
MAP_MODE = {"online": 0, "offline": 1}
MAP_TSRC = {"ntp": 0, "rtc": 1, "invalid": 2}

conn = db.connect()
db.wait_for_schema(conn)
conn.autocommit = True


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

    # Opportunistic presence/firmware tracking - "fw" only ever appears on
    # event payloads, never on heartbeats, so this is the only place it can
    # be captured. Runs regardless of whether the insert below turns out to
    # be a duplicate, since it's just presence + version, not the event itself.
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO devices (id, status, last_seen_at, fw)
                VALUES (%s, 'online', %s, %s)
                ON CONFLICT(id) DO UPDATE SET status = 'online', last_seen_at = EXCLUDED.last_seen_at, fw = EXCLUDED.fw
                """,
                (device_id, now, data.get("fw") or None),
            )
    except Exception as err:
        print(f"Device fw/presence update error: {err}", flush=True)

    # Translate strings to integers (defaulting to safe values if undefined)
    res_int = MAP_RESULT.get(data.get("res"), 1)   # Default: 1 (unknown)
    dir_int = MAP_DIR.get(data.get("dir"), 0)      # Default: 0 (in)
    mode_int = MAP_MODE.get(data.get("mode"), 0)   # Default: 0 (online)
    tsrc_int = MAP_TSRC.get(data.get("tsrc"), 2)   # Default: 2 (invalid)

    ts = data.get("ts")
    # Sanity Check: If timestamp is in the future (>10 mins) or before 2025, flag as invalid
    if ts is None or ts > (now + 600) or ts < 1735689600:
        print(f"[TIMESTAMP ANOMALY] Device {device_id} sent suspect ts: {ts}. Overriding tsrc to invalid.", flush=True)
        tsrc_int = 2  # TSRC_INVALID

    # Find the employee_id associated with this UID
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
        (device_id, seq, uid, employee_id, ts_utc, ts_source, dir, result, mode, ingested_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """
    values = (device_id, data.get("seq"), data.get("uid"), employee_id, ts, tsrc_int, dir_int, res_int, mode_int, now)

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
        INSERT INTO devices (id, status, last_seen_at)
        VALUES (%s, %s, %s)
        ON CONFLICT(id) DO UPDATE SET status = EXCLUDED.status, last_seen_at = EXCLUDED.last_seen_at
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

    # Upsert (not a blind UPDATE) so a heartbeat that happens to arrive
    # before this device's first /status message doesn't just silently
    # touch zero rows and lose the data.
    query = """
        INSERT INTO devices (id, status, last_seen_at, queue_depth, heap_free, queue_overflow, uptime_s)
        VALUES (%s, 'online', %s, %s, %s, %s, %s)
        ON CONFLICT(id) DO UPDATE SET
            status = 'online',
            last_seen_at = EXCLUDED.last_seen_at,
            queue_depth = EXCLUDED.queue_depth,
            heap_free = EXCLUDED.heap_free,
            queue_overflow = EXCLUDED.queue_overflow,
            uptime_s = EXCLUDED.uptime_s
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

    # OTA responses (ota_downloading / ota_ok_rebooting / ota_failed / ...)
    # get persisted so the panel can show update progress per device, same
    # pattern as the heartbeat/fw tracking above. Other command responses
    # (open_ok, rebooting, sync_triggered) are transient acks with nothing
    # meaningful to store long-term.
    if payload.startswith("ota_"):
        now = now_s()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO devices (id, status, last_seen_at, ota_status, ota_updated_at)
                    VALUES (%s, 'online', %s, %s, %s)
                    ON CONFLICT(id) DO UPDATE SET
                        status = 'online',
                        last_seen_at = EXCLUDED.last_seen_at,
                        ota_status = EXCLUDED.ota_status,
                        ota_updated_at = EXCLUDED.ota_updated_at
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
