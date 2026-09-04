"""PdksReportView is 100% raw SQL, no ORM guarantees - tests assert on computed aggregates, not just status codes."""
import os
from datetime import datetime, timezone as dt_timezone
from unittest.mock import patch

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import AuditLog
from cards.models import Card, Employee
from core.models import AccessEvent, Firmware
from core.test_utils import AuthenticatedAPITestCase
from devices.models import Device

# Lands both events on the same Europe/Istanbul calendar day - report groups by working_date.
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


class FirmwareUploadTests(AuthenticatedAPITestCase):
    """New version sets created_by; re-upload sets updated_by only. Cleans up written files."""

    def _cleanup_firmware_file(self, version):
        path = os.path.join(settings.FIRMWARE_DIR, f"firmware_{version}.bin")
        if os.path.exists(path):
            os.remove(path)

    def _upload(self, version, content=b"dummy-firmware-bytes"):
        self.addCleanup(self._cleanup_firmware_file, version)
        upload = SimpleUploadedFile(f"{version}.bin", content, content_type="application/octet-stream")
        return self.client.post(
            "/api/firmware/upload", {"version": version, "file": upload}, format="multipart"
        )

    def test_upload_new_version_creates_firmware_and_sets_created_by(self):
        response = self._upload("9.9.1-test")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)

        firmware = Firmware.objects.get(version="9.9.1-test")
        self.assertEqual(firmware.created_by_id, self.operator.id)
        self.assertIsNone(firmware.updated_by_id)
        self.assertEqual(firmware.size, len(b"dummy-firmware-bytes"))

        entry = AuditLog.objects.get(action="firmware.create")
        self.assertEqual(entry.operator_id, self.operator.id)

    def test_reupload_same_version_updates_and_sets_updated_by_not_created_by(self):
        self._upload("9.9.2-test", content=b"first-cut")
        firmware = Firmware.objects.get(version="9.9.2-test")
        original_created_by_id = firmware.created_by_id
        self.assertEqual(original_created_by_id, self.operator.id)

        response = self._upload("9.9.2-test", content=b"second-cut-longer-content")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)

        firmware.refresh_from_db()
        self.assertEqual(firmware.created_by_id, original_created_by_id)  # not clobbered by 2nd upload
        self.assertEqual(firmware.updated_by_id, self.operator.id)
        self.assertEqual(firmware.size, len(b"second-cut-longer-content"))

        self.assertTrue(AuditLog.objects.filter(action="firmware.update").exists())

    def test_upload_rejects_non_bin_extension(self):
        upload = SimpleUploadedFile("firmware.txt", b"not-a-binary", content_type="text/plain")
        response = self.client.post(
            "/api/firmware/upload", {"version": "9.9.3-test", "file": upload}, format="multipart"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(Firmware.objects.filter(version="9.9.3-test").exists())

    def test_upload_invalid_version_format_returns_400(self):
        upload = SimpleUploadedFile("bad.bin", b"content", content_type="application/octet-stream")
        response = self.client.post(
            "/api/firmware/upload", {"version": "not a valid version!", "file": upload}, format="multipart"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class FirmwareDownloadTests(APITestCase):
    """download is AllowAny - the ESP32 hits this and can't hold a JWT."""

    def setUp(self):
        self.version = "9.9.4-test"
        self.filename = f"firmware_{self.version}.bin"
        self.file_path = os.path.join(settings.FIRMWARE_DIR, self.filename)
        self.content = b"fake-esp32-binary-content"
        with open(self.file_path, "wb") as f:
            f.write(self.content)
        self.addCleanup(lambda: os.path.exists(self.file_path) and os.remove(self.file_path))

        self.firmware = Firmware.objects.create(
            version=self.version, filename=self.filename, md5="a" * 32, size=len(self.content),
        )

    def test_download_without_authentication_succeeds_and_streams_the_file(self):
        response = self.client.get(f"/api/firmware/{self.version}/download")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(b"".join(response.streaming_content), self.content)

    def test_download_unknown_version_returns_404(self):
        response = self.client.get("/api/firmware/does-not-exist/download")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_download_missing_file_on_disk_returns_404(self):
        os.remove(self.file_path)
        response = self.client.get(f"/api/firmware/{self.version}/download")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class EventUnauthenticatedAccessTests(APITestCase):
    """Unlike firmware download, EventViewSet has no AllowAny carve-out."""

    def test_list_without_authentication_returns_401(self):
        response = self.client.get("/api/events")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class EventListTests(AuthenticatedAPITestCase):
    def test_list_returns_events_newest_first_with_employee_joined(self):
        # raw SQL joins uid -> cards.uid -> employee_id, not an AccessEvent FK - needs a real Card row.
        employee = Employee.objects.create(full_name="Newest First Test")
        Card.objects.create(uid="EVT2", employee=employee)

        AccessEvent.objects.create(device_id="GATE-K3-001", seq=101, uid="EVT1", ts_utc=1000)
        AccessEvent.objects.create(
            device_id="GATE-K3-001", seq=102, uid="EVT2", ts_utc=1001, employee_id=employee.id
        )

        response = self.client.get("/api/events")
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        seqs = [row["seq"] for row in response.data]
        self.assertLess(seqs.index(102), seqs.index(101))  # ORDER BY a.id DESC

        newest = next(row for row in response.data if row["seq"] == 102)
        self.assertEqual(newest["full_name"], "Newest First Test")


class BaseModelSaveBehaviorTests(TestCase):
    """save() force-injects updated_at into update_fields - auto_now skips it otherwise."""

    def test_partial_save_with_update_fields_still_refreshes_updated_at(self):
        device = Device.objects.create(id="SAVE-TEST-01", name="Original")
        original_updated_at = device.updated_at

        device.name = "Changed"
        device.save(update_fields=["name"])  # updated_at deliberately NOT listed

        device.refresh_from_db()
        self.assertEqual(device.name, "Changed")
        self.assertGreater(device.updated_at, original_updated_at)


class AccessEventConstraintTests(TestCase):
    def test_duplicate_device_id_and_seq_raises_integrity_error(self):
        """uniq_device_seq is what collector's duplicate-seq handling relies on."""
        AccessEvent.objects.create(device_id="GATE-K3-001", seq=1)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                AccessEvent.objects.create(device_id="GATE-K3-001", seq=1)

        AccessEvent.objects.create(device_id="GATE-K3-002", seq=1)  # constraint is on the (device_id, seq) pair
