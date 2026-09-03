"""
Collector için bağlantı yönetimi. Tablo oluşturma artık Django backend'in
migration'larının işi (eski db.js schema bloğunun karşılığı) - bu modül
sadece bir bağlantı açıyor ve collector MQTT mesajlarını işlemeye başlamadan
önce tabloların var olmasını bekliyor; collector.js ile db.js arasındaki
eski `await pool.ready` el sıkışmasının aynısı.
"""
import os
import time

import psycopg2

DB_HOST = os.environ.get("DB_HOST", "127.0.0.1")
DB_NAME = os.environ.get("DB_NAME", "pdks")
DB_USER = os.environ.get("DB_USER", "pdks")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "pdks_password")
DB_PORT = os.environ.get("DB_PORT", "5432")


def connect(retries=20, delay_seconds=3):
    """Yavaş açılan ya da anlık olarak çözümlenemeyen bir DB host'un (örn.
    compose'un ilk birkaç saniyesinde 'could not translate host name
    "postgres"') süreci çökertmesine izin vermek yerine ilk bağlantıyı
    tekrar dener. Sadece OperationalError'ı (bağlantı/DNS/auth seviyesi
    hatalar) yakalar - başka her şey gerçek bir bug, hemen görünür olmalı."""
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            conn = psycopg2.connect(
                host=DB_HOST, dbname=DB_NAME, user=DB_USER, password=DB_PASSWORD, port=DB_PORT
            )
            # Baştan autocommit: aşağıdaki wait_for_schema() bir döngüde düz
            # SELECT'lerle polling yapıyor, "henüz hazır değil" sonucu bir
            # exception değil - normal, neredeyse 0-satırlık bir cevap, yani
            # poll'lar arasında o sorgunun örtük transaction'ını kapatan bir
            # şey yok. autocommit olmayan bir bağlantıda ilkinden sonraki her
            # poll hâlâ açık olan aynı transaction'ın snapshot'ını yeniden
            # kullanırdı, bu da başka bir bağlantının oluşturduğu schema'yı
            # asla göremeyebilirdi - autocommit, her çağıran yerin her
            # statement'ten sonra commit/rollback yapmayı hatırlamasına
            # güvenmek yerine bu hata modunu tamamen ortadan kaldırıyor.
            conn.autocommit = True
            return conn
        except psycopg2.OperationalError as err:
            last_err = err
            print(f"[db] connect failed (attempt {attempt}/{retries}): {err}", flush=True)
            time.sleep(delay_seconds)
    raise RuntimeError(f"Could not connect to database after {retries} attempts: {last_err}")


def wait_for_schema(conn, retries=30, delay_seconds=2):
    """Backend'in açılışıyla yarışmak yerine, Django backend'in
    migration'larının oluşturduğu tabloların gerçekten var olmasını bekleyerek poll eder."""
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
