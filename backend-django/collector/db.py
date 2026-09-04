"""Collector bağlantı yönetimi - tablo oluşturma Django migration'larının işi, burası sadece bağlanıp bekler."""
import os
import time

import psycopg2

DB_HOST = os.environ.get("DB_HOST", "127.0.0.1")
DB_NAME = os.environ.get("DB_NAME", "pdks")
DB_USER = os.environ.get("DB_USER", "pdks")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "pdks_password")
DB_PORT = os.environ.get("DB_PORT", "5432")


def connect(retries=20, delay_seconds=3):
    """DB host henüz hazır değilse (DNS/bağlantı) ilk bağlantıyı tekrar dener - sadece OperationalError'ı yakalar."""
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            conn = psycopg2.connect(
                host=DB_HOST, dbname=DB_NAME, user=DB_USER, password=DB_PASSWORD, port=DB_PORT
            )
            # autocommit: yoksa wait_for_schema()'nun poll'ları aynı eski transaction snapshot'ını görür, yeni schema'yı kaçırır.
            conn.autocommit = True
            return conn
        except psycopg2.OperationalError as err:
            last_err = err
            print(f"[db] connect failed (attempt {attempt}/{retries}): {err}", flush=True)
            time.sleep(delay_seconds)
    raise RuntimeError(f"Could not connect to database after {retries} attempts: {last_err}")


def wait_for_schema(conn, retries=30, delay_seconds=2):
    """Backend'in migration'larının tabloları oluşturmasını poll ederek bekler."""
    for attempt in range(1, retries + 1):
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT to_regclass('public.access_events'), to_regclass('public.devices'), "
                    "to_regclass('public.cards')"
                )
                access_events, devices, cards = cur.fetchone()
                if access_events and devices and cards:
                    conn.commit()  # psycopg2'nin SELECT için açtığı örtük transaction'ı kapat
                    return
        except Exception as err:
            print(f"[db] schema check failed (attempt {attempt}/{retries}): {err}", flush=True)
            conn.rollback()
        print(f"[db] waiting for backend to create schema... ({attempt}/{retries})", flush=True)
        time.sleep(delay_seconds)
    raise RuntimeError("Timed out waiting for database schema to be created by the backend.")
