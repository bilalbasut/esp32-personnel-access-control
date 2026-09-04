"""Backend test suite - PDKS report endpoint (core/views.py PdksReportView).

This view is 100% raw SQL (a CTE chain run straight through
connection.cursor()), so nothing here is caught by Django's ORM-level
guarantees - a typo in a column name or a broken window-function partition
would only show up by actually running the query. These tests create real
AccessEvent/Employee rows and assert on the computed aggregates, not just
status codes.

All test classes authenticate via AuthenticatedAPITestCase (core/test_utils.py) -
DEFAULT_PERMISSION_CLASSES=[IsAuthenticated] (config/settings.py) now guards
this endpoint too, so an unauthenticated self.client would just get 401
before any of the report logic under test ever ran.
"""
from datetime import datetime, timezone as dt_timezone

from rest_framework import status

from cards.models import Employee
from core.models import AccessEvent
from core.test_utils import AuthenticatedAPITestCase

# Fixed instant chosen so that both the check-in and check-out below land on
# the same Europe/Istanbul calendar day (default REPORT_TZ, UTC+3) - the
# report groups by working_date, so a value near a day boundary would make
# the "same day" assumption in these tests flaky.
CHECK_IN_TS = int(datetime(2024, 1, 15, 12, 0, 0, tzinfo=dt_timezone.utc).timestamp())
CHECK_OUT_TS = CHECK_IN_TS + 3600  # 1 hour later


class PdksReportValidationTests(AuthenticatedAPITestCase):
    def test_missing_start_or_end_ts_returns_400(self):
        response = self.client.get("/api/reports/pdks")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        response = self.client.get("/api/reports/pdks", {"start_ts": CHECK_IN_TS})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_non_integer_employee_id_returns_400(self):
        response = self.client.get("/api/reports/pdks", {
            "start_ts": CHECK_IN_TS, "end_ts": CHECK_OUT_TS, "employee_id": "not-a-number",
        })
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class PdksReportComputationTests(AuthenticatedAPITestCase):
    def setUp(self):
        super().setUp()
        self.employee = Employee.objects.create(full_name="Rear Admiral Hopper", department="Engineering")
        self.other_employee = Employee.objects.create(full_name="Someone Else")

        # MAIN zone = device_id starting with "GATE-K3-" (see PdksReportView.get()).
        AccessEvent.objects.create(
            device_id="GATE-K3-001", seq=1, uid="AABBCC", employee_id=self.employee.id,
            ts_utc=CHECK_IN_TS, ts_source=0, dir=0, result=0, mode=0, ingested_at=CHECK_IN_TS,
        )
        AccessEvent.objects.create(
            device_id="GATE-K3-001", seq=2, uid="AABBCC", employee_id=self.employee.id,
            ts_utc=CHECK_OUT_TS, ts_source=0, dir=1, result=0, mode=0, ingested_at=CHECK_OUT_TS,
        )

    def _get_report(self, **params):
        params.setdefault("start_ts", CHECK_IN_TS - 10)
        params.setdefault("end_ts", CHECK_OUT_TS + 10)
        return self.client.get("/api/reports/pdks", params)

    def test_computes_first_in_last_out_and_total_work_seconds(self):
        response = self._get_report()
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)

        rows = [r for r in response.data if r["employee_id"] == self.employee.id]
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["first_in_main"], CHECK_IN_TS)
        self.assertEqual(row["last_out_main"], CHECK_OUT_TS)
        self.assertEqual(row["total_work_seconds"], 3600)
        self.assertEqual(row["full_name"], "Rear Admiral Hopper")

    def test_events_outside_the_requested_window_are_excluded(self):
        response = self._get_report(start_ts=CHECK_OUT_TS + 100, end_ts=CHECK_OUT_TS + 200)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([r for r in response.data if r["employee_id"] == self.employee.id], [])

    def test_employee_id_filter_returns_only_that_employee(self):
        AccessEvent.objects.create(
            device_id="GATE-K3-001", seq=3, uid="DDEEFF", employee_id=self.other_employee.id,
            ts_utc=CHECK_IN_TS, ts_source=0, dir=0, result=0, mode=0, ingested_at=CHECK_IN_TS,
        )

        response = self._get_report(employee_id=self.employee.id)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        employee_ids = {r["employee_id"] for r in response.data}
        self.assertEqual(employee_ids, {self.employee.id})

    def test_non_granted_results_are_excluded(self):
        # result codes other than 0 (granted) / 4 (manual) - e.g. 1 (unknown) -
        # must not count as a real in/out event.
        AccessEvent.objects.create(
            device_id="GATE-K3-001", seq=4, uid="AABBCC", employee_id=self.employee.id,
            ts_utc=CHECK_IN_TS + 60, ts_source=0, dir=0, result=1, mode=0, ingested_at=CHECK_IN_TS + 60,
        )
        response = self._get_report()
        row = next(r for r in response.data if r["employee_id"] == self.employee.id)
        # Still just the original in/out pair - the "unknown" result event is ignored.
        self.assertEqual(row["total_work_seconds"], 3600)

    def test_csv_format_returns_attachment_with_expected_header(self):
        response = self._get_report(format="csv")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response["Content-Type"], "text/csv; charset=utf-8")
        self.assertIn('attachment; filename="pdks_raporu.csv"', response["Content-Disposition"])

        content = response.content.decode("utf-8")
        header, *rows = content.splitlines()
        self.assertEqual(
            header,
            "Personel No,Ad Soyad,Departman,Tarih,İlk Giriş,Son Çıkış,"
            "Toplam Çalışma Süresi,Yemek Molası,Mola",
        )
        self.assertTrue(any("Rear Admiral Hopper" in row for row in rows))
        # 3600s of work must render as HH:MM:SS, not raw seconds.
        self.assertTrue(any("01:00:00" in row for row in rows))
