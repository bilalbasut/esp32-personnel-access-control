"""
Connection handling for the collector. Table creation itself is owned by
the Django backend's migrations now (equivalent of the old db.js schema
block) - this module just opens a connection and waits for the tables to
exist before the collector starts consuming MQTT messages, mirroring the
old `await pool.ready` handshake between collector.js and db.js.
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
    """Retries the initial connection instead of letting a slow-starting or
    momentarily unresolvable DB host (e.g. 'could not translate host name
    "postgres"' during compose's first few seconds) crash the process. Only
    catches OperationalError (connection/DNS/auth-level failures) - anything
    else is a real bug and should surface immediately."""
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            conn = psycopg2.connect(
                host=DB_HOST, dbname=DB_NAME, user=DB_USER, password=DB_PASSWORD, port=DB_PORT
            )
            # Autocommit from the start: wait_for_schema() below polls with
            # plain SELECTs in a loop, and a "not ready yet" result isn't an
            # exception - it's a normal 0-row-ish answer, so nothing closed
            # that query's implicit transaction between polls. Under a
            # non-autocommit connection that left every poll after the
            # first re-using one still-open transaction's snapshot, which
            # can just never observe schema created by a different
            # connection afterwards - autocommit removes that whole failure
            # mode instead of relying on every call site remembering to
            # commit/rollback after each statement.
            conn.autocommit = True
            return conn
        except psycopg2.OperationalError as err:
            last_err = err
            print(f"[db] connect failed (attempt {attempt}/{retries}): {err}", flush=True)
            time.sleep(delay_seconds)
    raise RuntimeError(f"Could not connect to database after {retries} attempts: {last_err}")


def wait_for_schema(conn, retries=30, delay_seconds=2):
    """Polls until the tables the Django backend's migrations create are
    actually present, instead of racing backend startup."""
    for attempt in range(1, retries + 1):
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT to_regclass('public.access_events'), to_regclass('public.devices'), "
                    "to_regclass('public.cards')"
                )
                access_events, devices, cards = cur.fetchone()
                if access_events and devices and cards:
                    conn.commit()  # close the implicit transaction psycopg2 opened for the SELECT
                    return
        except Exception as err:
            print(f"[db] schema check failed (attempt {attempt}/{retries}): {err}", flush=True)
            conn.rollback()
        print(f"[db] waiting for backend to create schema... ({attempt}/{retries})", flush=True)
        time.sleep(delay_seconds)
    raise RuntimeError("Timed out waiting for database schema to be created by the backend.")
