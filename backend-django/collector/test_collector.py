"""Backend test suite - collector's raw-SQL insert paths (collector.py).

The collector is a standalone script (not part of the Django app), talking
to Postgres via raw psycopg2 and to Mosquitto via paho-mqtt - there's no
Django test runner, no APITestCase, and no broker/DB available in a plain
`python -m unittest` run. So instead of a real DB, every handler is tested
against a fake connection/cursor that just records the SQL text and params
it was called with, and asserts on those.

This is deliberately the regression test for the bug we just fixed: every
one of the four upsert queries below (device fw/presence, /status, /hb,
OTA cmd/res) must set created_at/updated_at explicitly, because these
INSERTs bypass Django's ORM entirely - auto_now_add/auto_now never run.
Devices now inherits core/models.py BaseModel, whose created_at/updated_at
DO carry a Postgres-level db_default (see BaseModel docstring) - that
covers the plain INSERT case (a first-ever row for a device), but a
db_default is NOT consulted by `ON CONFLICT ... DO UPDATE SET ...`: if
updated_at isn't named in that SET clause, an existing row's updated_at
simply stays at its old value instead of refreshing. So this test's
concern is still real for the update path, even though the insert path
now has a safety net it didn't have before.

Run directly (needs the collector's own venv/deps - paho-mqtt, psycopg2):
    cd collector && python -m unittest test_collector.py -v
"""
import json
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import db  # noqa: E402  - local module (collector/db.py)

# collector.py opens a real DB connection at import time
# (`conn = db.connect()` / `db.wait_for_schema(conn)` at module scope), so
# db.connect/wait_for_schema must be patched *before* collector is
# imported anywhere in the process - there's no DB running under this
# test. Patched only around the import itself; every test below swaps in
# its own FakeConnection via `collector.conn` (see FakeDbTestCase).
with patch.object(db, "connect", return_value=MagicMock()), \
     patch.object(db, "wait_for_schema", return_value=None):
    import collector  # noqa: E402

import psycopg2  # noqa: E402


class FakeCursor:
    """Records every execute() call; can be told to raise on a specific one
    (e.g. simulating the UniqueViolation collector.py explicitly handles)."""

    def __init__(self, fetchone_result=None, raise_on_query_substring=None, raise_exc=None):
        self.executed = []  # list of (query, params)
        self._fetchone_result = fetchone_result
        self._raise_on_query_substring = raise_on_query_substring
        self._raise_exc = raise_exc

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query, params=None):
        if self._raise_on_query_substring and self._raise_on_query_substring in query:
            raise self._raise_exc
        self.executed.append((query, params))

    def fetchone(self):
        return self._fetchone_result


class FakeConnection:
    def __init__(self, cursor):
        self._cursor = cursor
        self.rollback_called = False

    def cursor(self):
        return self._cursor

    def rollback(self):
        self.rollback_called = True


class FakeDbTestCase(unittest.TestCase):
    """Base class that swaps collector's module-level `conn` global for a
    fake one for the duration of each test. Handler functions look up
    `conn` by name at call time, so this is enough - no re-import needed."""

    def setUp(self):
        self.cursor = FakeCursor()
        self.conn = FakeConnection(self.cursor)
        patcher = patch.object(collector, "conn", self.conn)
        patcher.start()
        self.addCleanup(patcher.stop)


class HandleEventTests(FakeDbTestCase):
    def setUp(self):
        super().setUp()
        # handle_event's employee lookup (`SELECT employee_id FROM cards ...`)
        # calls cur.fetchone() - give it something to find.
        self.cursor._fetchone_result = (42,)
        self.client = MagicMock()

    def _payload(self, **overrides):
        data = {
            "seq": 7, "uid": "AABBCC", "res": "granted", "dir": "in",
            "mode": "online", "tsrc": "ntp", "ts": collector.now_s(), "fw": "1.9.0",
        }
        data.update(overrides)
        return json.dumps(data)

    def test_device_upsert_sets_created_and_updated_at(self):
        """Regression test for the NOT NULL violation: the fw/presence
        upsert must explicitly set created_at/updated_at via NOW(), since
        this INSERT never goes through Django's auto_now_add/auto_now."""
        collector.handle_event(self.client, "GATE-K3-001", self._payload())

        device_upsert_query = self.cursor.executed[0][0]
        self.assertIn("INSERT INTO devices", device_upsert_query)
        self.assertIn("created_at", device_upsert_query)
        self.assertIn("updated_at", device_upsert_query)
        self.assertIn("NOW()", device_upsert_query)

    def test_translates_string_fields_to_smallints_and_resolves_employee(self):
        collector.handle_event(self.client, "GATE-K3-001", self._payload(
            res="granted", dir="in", mode="online", tsrc="ntp",
        ))

        insert_query, params = self.cursor.executed[-1]
        self.assertIn("INSERT INTO access_events", insert_query)
        # (device_id, seq, uid, employee_id, ts_utc, ts_source, dir, result, mode, ingested_at, raw_payload)
        self.assertEqual(params[3], 42)  # employee_id resolved from the fake cursor lookup
        self.assertEqual(params[5], 0)   # ts_source: ntp -> 0
        self.assertEqual(params[6], 0)   # dir: in -> 0
        self.assertEqual(params[7], 0)   # result: granted -> 0
        self.assertEqual(params[8], 0)   # mode: online -> 0

    def test_unknown_string_values_fall_back_to_safe_defaults(self):
        collector.handle_event(self.client, "GATE-K3-001", self._payload(
            res="not-a-real-code", dir="sideways", mode="???", tsrc="???",
        ))
        _, params = self.cursor.executed[-1]
        self.assertEqual(params[5], 2)  # ts_source default: invalid
        self.assertEqual(params[6], 0)  # dir default: in
        self.assertEqual(params[7], 1)  # result default: unknown
        self.assertEqual(params[8], 0)  # mode default: online

    def test_future_timestamp_is_flagged_invalid(self):
        collector.handle_event(self.client, "GATE-K3-001", self._payload(
            ts=collector.now_s() + 10_000,  # more than 10 minutes ahead
        ))
        _, params = self.cursor.executed[-1]
        self.assertEqual(params[5], 2)  # ts_source forced to invalid

    def test_stale_pre_2025_timestamp_is_flagged_invalid(self):
        collector.handle_event(self.client, "GATE-K3-001", self._payload(ts=1_700_000_000))
        _, params = self.cursor.executed[-1]
        self.assertEqual(params[5], 2)

    def test_sends_ack_on_successful_insert(self):
        collector.handle_event(self.client, "GATE-K3-001", self._payload(seq=99))
        self.client.publish.assert_called_once()
        topic, payload = self.client.publish.call_args[0][:2]
        self.assertEqual(topic, "pdks/merkez/dev/GATE-K3-001/event/ack")
        self.assertEqual(json.loads(payload), {"ack_seq": 99})

    def test_duplicate_seq_still_acks_and_rolls_back_without_crashing(self):
        cursor = FakeCursor(
            fetchone_result=(42,),
            raise_on_query_substring="INSERT INTO access_events",
            raise_exc=psycopg2.errors.UniqueViolation(),
        )
        fake_conn = FakeConnection(cursor)
        with patch.object(collector, "conn", fake_conn):
            collector.handle_event(self.client, "GATE-K3-001", self._payload(seq=5))

        self.assertTrue(fake_conn.rollback_called)
        self.client.publish.assert_called_once()  # ACK still sent for a duplicate

    def test_invalid_json_payload_is_ignored(self):
        collector.handle_event(self.client, "GATE-K3-001", "not json")
        self.assertEqual(self.cursor.executed, [])
        self.client.publish.assert_not_called()


class HandleStatusTests(FakeDbTestCase):
    def test_upsert_sets_created_and_updated_at(self):
        collector.handle_status("GATE-K3-001", "online")
        query, params = self.cursor.executed[0]
        self.assertIn("INSERT INTO devices", query)
        self.assertIn("created_at", query)
        self.assertIn("updated_at", query)
        self.assertIn("NOW()", query)
        self.assertEqual(params[0], "GATE-K3-001")
        self.assertEqual(params[1], "online")


class HandleHeartbeatTests(FakeDbTestCase):
    def test_upsert_sets_created_and_updated_at_and_metrics(self):
        payload = json.dumps({"queue": 3, "heap": 45000, "qOverflow": 0, "uptime": 12345})
        collector.handle_heartbeat("GATE-K3-001", payload)

        query, params = self.cursor.executed[0]
        self.assertIn("INSERT INTO devices", query)
        self.assertIn("created_at", query)
        self.assertIn("updated_at", query)
        self.assertIn("NOW()", query)
        # params = (device_id, now, queue, heap, qOverflow, uptime)
        self.assertEqual(params[0], "GATE-K3-001")
        self.assertIsInstance(params[1], int)
        self.assertGreater(params[1], 0)
        self.assertEqual(params[2:], (3, 45000, 0, 12345))

    def test_invalid_json_stores_presence_only_without_crashing(self):
        collector.handle_heartbeat("GATE-K3-001", "not json")
        query, params = self.cursor.executed[0]
        self.assertIn("INSERT INTO devices", query)
        # queue/heap/qOverflow/uptime all fall back to None, not an exception.
        self.assertEqual(params[2:], (None, None, None, None))


class HandleCmdResTests(FakeDbTestCase):
    def test_ota_status_is_persisted_with_created_and_updated_at(self):
        collector.handle_cmd_res("GATE-K3-001", "ota_downloading")
        self.assertEqual(len(self.cursor.executed), 1)
        query, params = self.cursor.executed[0]
        self.assertIn("INSERT INTO devices", query)
        self.assertIn("created_at", query)
        self.assertIn("updated_at", query)
        self.assertIn("NOW()", query)
        self.assertEqual(params[2], "ota_downloading")

    def test_non_ota_responses_are_not_persisted(self):
        collector.handle_cmd_res("GATE-K3-001", "open_ok")
        self.assertEqual(self.cursor.executed, [])


class TranslationMapTests(unittest.TestCase):
    """The maps are the single source of truth for string<->SMALLINT
    translation between firmware payloads and Postgres - a typo here would
    silently misclassify every event of that kind."""

    def test_map_result(self):
        self.assertEqual(collector.MAP_RESULT, {
            "granted": 0, "unknown": 1, "expired": 2, "schedule": 3, "manual": 4,
        })

    def test_map_dir(self):
        self.assertEqual(collector.MAP_DIR, {"in": 0, "out": 1})

    def test_map_mode(self):
        self.assertEqual(collector.MAP_MODE, {"online": 0, "offline": 1})

    def test_map_tsrc(self):
        self.assertEqual(collector.MAP_TSRC, {"ntp": 0, "rtc": 1, "invalid": 2})


if __name__ == "__main__":
    unittest.main()
