"""Backend test suite - Device CRUD via AuditedModelViewSet (core/audit_viewset.py).

DeviceViewSet no longer writes its own perform_create/update/destroy - it
gets created_by/updated_by/deleted_by attribution and AuditLog diff entries
for free from the AuditedModelViewSet mixin (devices/views.py). Device is
also the one ViewSet that uses the mixin with ZERO extra side effects
(unlike Card, which also republishes ACL - see cards/tests.py
CardAttributionTests for that wrapped case), so it's the cleanest place to
pin down the mixin's own behaviour.

DeviceUnauthenticatedAccessTests below is the regression test for the other
half of this pass: DEFAULT_PERMISSION_CLASSES=[IsAuthenticated]
(config/settings.py) must actually reject an unauthenticated request before
it reaches the view, not just leave attribution fields empty.
"""
from unittest.mock import patch

from django.test import override_settings
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import AuditLog
from core.models import Firmware
from core.test_utils import AuthenticatedAPITestCase
from devices.models import Device


class DeviceAttributionTests(AuthenticatedAPITestCase):
    def test_create_sets_created_by_to_the_authenticated_operator(self):
        response = self.client.post(
            "/api/devices", {"id": "GATE-TEST-01", "name": "Test Gate"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)

        device = Device.objects.get(id="GATE-TEST-01")
        self.assertEqual(device.created_by_id, self.operator.id)
        self.assertIsNone(device.updated_by_id)

    def test_create_writes_an_audit_log_entry_with_the_field_diff(self):
        self.client.post(
            "/api/devices", {"id": "GATE-TEST-02", "name": "Test Gate 2"}, format="json"
        )

        entry = AuditLog.objects.get(action="device.create")
        self.assertEqual(entry.operator_id, self.operator.id)
        self.assertEqual(entry.created_by_id, self.operator.id)
        # create-time diffs are logged as "None -> value" for every non-empty field.
        self.assertEqual(entry.details["changes"]["id"], {"old": None, "new": "GATE-TEST-02"})
        self.assertEqual(entry.details["changes"]["name"], {"old": None, "new": "Test Gate 2"})

    def test_update_sets_updated_by_and_logs_only_the_changed_field(self):
        device = Device.objects.create(id="GATE-TEST-03", name="Old Name", floor=1)

        response = self.client.patch(
            f"/api/devices/{device.id}", {"name": "New Name"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)

        device.refresh_from_db()
        self.assertEqual(device.name, "New Name")
        self.assertEqual(device.updated_by_id, self.operator.id)
        self.assertIsNone(device.created_by_id)  # this row was created directly via the ORM, not through the API

        entry = AuditLog.objects.get(action="device.update")
        self.assertEqual(entry.details["changes"], {"name": {"old": "Old Name", "new": "New Name"}})
        self.assertNotIn("floor", entry.details["changes"])  # untouched field must not show up in the diff

    def test_update_with_no_actual_field_change_writes_no_audit_log(self):
        device = Device.objects.create(id="GATE-TEST-04", name="Same Name")

        response = self.client.patch(
            f"/api/devices/{device.id}", {"name": "Same Name"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertFalse(AuditLog.objects.filter(action="device.update").exists())

    def test_delete_soft_deletes_and_sets_deleted_by(self):
        device = Device.objects.create(id="GATE-TEST-05", name="To Delete")

        response = self.client.delete(f"/api/devices/{device.id}")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        # ActiveManager (core/models.py) hides soft-deleted rows from the default manager...
        self.assertFalse(Device.objects.filter(id="GATE-TEST-05").exists())
        # ...but the row itself, and who deleted it, is preserved.
        preserved = Device.all_objects.get(id="GATE-TEST-05")
        self.assertIsNotNone(preserved.deleted_at)
        self.assertEqual(preserved.deleted_by_id, self.operator.id)

        entry = AuditLog.objects.get(action="device.delete")
        self.assertEqual(entry.operator_id, self.operator.id)
        self.assertEqual(entry.target_repr, str(preserved))


class DeviceUnauthenticatedAccessTests(APITestCase):
    """Deliberately does NOT use AuthenticatedAPITestCase - the whole point
    is an unauthenticated self.client."""

    def test_list_devices_without_token_returns_401(self):
        response = self.client.get("/api/devices")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_create_device_without_token_returns_401_and_creates_nothing(self):
        response = self.client.post("/api/devices", {"id": "SHOULD-NOT-EXIST"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertFalse(Device.objects.filter(id="SHOULD-NOT-EXIST").exists())


class DeviceCommandActionTests(AuthenticatedAPITestCase):
    """DeviceViewSet.send_command (devices/views.py) - not part of
    AuditedModelViewSet's standard create/update/destroy, so it still hand-
    calls log_action() itself; these confirm that call actually happens,
    and that a bad command or a broken MQTT publish are handled distinctly
    (400 for a validation problem the caller can fix, 500 for an
    infrastructure problem they can't)."""

    def setUp(self):
        super().setUp()
        self.device = Device.objects.create(id="GATE-CMD-01", name="Command Test Gate")

    @patch("core.mqtt_utils.publish")
    def test_valid_command_publishes_and_logs(self, mock_publish):
        response = self.client.post(
            f"/api/devices/{self.device.id}/command", {"cmd": "open"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data["status"], "queued")

        mock_publish.assert_called_once()
        topic, payload = mock_publish.call_args[0][:2]
        self.assertEqual(topic, f"pdks/merkez/dev/{self.device.id}/cmd")
        self.assertIn('"cmd": "open"', payload)

        entry = AuditLog.objects.get(action="device.command")
        self.assertEqual(entry.operator_id, self.operator.id)
        self.assertEqual(entry.details["cmd"], "open")

    def test_invalid_command_returns_400_and_does_not_publish(self):
        with patch("core.mqtt_utils.publish") as mock_publish:
            response = self.client.post(
                f"/api/devices/{self.device.id}/command", {"cmd": "not-a-real-command"}, format="json"
            )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        mock_publish.assert_not_called()

    @patch("core.mqtt_utils.publish", side_effect=Exception("broker unreachable"))
    def test_mqtt_publish_failure_returns_500_and_does_not_log(self, mock_publish):
        response = self.client.post(
            f"/api/devices/{self.device.id}/command", {"cmd": "reboot"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        # log_action() is called AFTER the publish succeeds (devices/views.py
        # send_command) - a broker failure must not leave a misleading "this
        # command was issued" audit trail behind.
        self.assertFalse(AuditLog.objects.filter(action="device.command").exists())


@override_settings(PANEL_BASE_URL="http://panel.test.local")
class DeviceOtaActionTests(AuthenticatedAPITestCase):
    """DeviceViewSet.ota (devices/views.py) - looks up a Firmware row,
    validates its md5, and builds the OTA download URL the ESP32 will hit
    (FirmwareViewSet.download, AllowAny - see core/tests.py
    FirmwareDownloadTests). Each failure mode here (unknown version, bad
    md5, unconfigured PANEL_BASE_URL) is deliberately a distinct guard in
    the view, not just a generic error path."""

    def setUp(self):
        super().setUp()
        self.device = Device.objects.create(id="GATE-OTA-01", name="OTA Test Gate")
        self.firmware = Firmware.objects.create(
            version="3.0.0-test", filename="firmware_3.0.0-test.bin", md5="b" * 32, size=1024,
        )

    @patch("core.mqtt_utils.publish")
    def test_valid_version_queues_ota_command_and_logs(self, mock_publish):
        response = self.client.post(
            f"/api/devices/{self.device.id}/ota", {"version": "3.0.0-test"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data["md5"], "b" * 32)
        self.assertIn("http://panel.test.local/api/firmware/3.0.0-test/download", response.data["ota_url"])

        mock_publish.assert_called_once()
        entry = AuditLog.objects.get(action="device.ota")
        self.assertEqual(entry.details["version"], "3.0.0-test")

    def test_unknown_firmware_version_returns_404(self):
        with patch("core.mqtt_utils.publish") as mock_publish:
            response = self.client.post(
                f"/api/devices/{self.device.id}/ota", {"version": "does-not-exist"}, format="json"
            )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        mock_publish.assert_not_called()

    def test_invalid_md5_length_returns_500(self):
        Firmware.objects.filter(version="3.0.0-test").update(md5="not-32-hex-chars")
        with patch("core.mqtt_utils.publish") as mock_publish:
            response = self.client.post(
                f"/api/devices/{self.device.id}/ota", {"version": "3.0.0-test"}, format="json"
            )
        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        mock_publish.assert_not_called()

    @override_settings(PANEL_BASE_URL="")
    def test_missing_panel_base_url_returns_500(self):
        with patch("core.mqtt_utils.publish") as mock_publish:
            response = self.client.post(
                f"/api/devices/{self.device.id}/ota", {"version": "3.0.0-test"}, format="json"
            )
        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        mock_publish.assert_not_called()
