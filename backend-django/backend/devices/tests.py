"""Device CRUD via AuditedModelViewSet - no extra side effects (unlike Card's ACL republish),
cleanest place to pin down the mixin's own behavior."""
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
    """Deliberately unauthenticated self.client."""

    def test_list_devices_without_token_returns_401(self):
        response = self.client.get("/api/devices")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_create_device_without_token_returns_401_and_creates_nothing(self):
        response = self.client.post("/api/devices", {"id": "SHOULD-NOT-EXIST"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertFalse(Device.objects.filter(id="SHOULD-NOT-EXIST").exists())


class DeviceCommandActionTests(AuthenticatedAPITestCase):
    """send_command hand-calls log_action() (not standard CRUD) - bad command is 400, broker failure is 500."""

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

    @patch("core.mqtt_utils.publish")
    def test_extra_payload_is_merged_into_the_mqtt_message(self, mock_publish):
        response = self.client.post(
            f"/api/devices/{self.device.id}/command",
            {"cmd": "settime", "payload": {"epoch": 1735689600}},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)

        _, payload = mock_publish.call_args[0][:2]
        self.assertIn('"epoch": 1735689600', payload)

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
        self.assertFalse(AuditLog.objects.filter(action="device.command").exists())  # no misleading audit trail


@override_settings(PANEL_BASE_URL="http://panel.test.local")
class DeviceOtaActionTests(AuthenticatedAPITestCase):
    """Each failure mode (unknown version, bad md5, missing PANEL_BASE_URL) is a distinct guard in the view."""

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

    @patch("core.mqtt_utils.publish")
    def test_version_with_leading_v_prefix_still_resolves(self, mock_publish):
        # Registry has "3.0.0-test" (no "v"); "v3.0.0-test" resolves via the lstrip("v") fallback.
        response = self.client.post(
            f"/api/devices/{self.device.id}/ota", {"version": "v3.0.0-test"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertIn("/api/firmware/3.0.0-test/download", response.data["ota_url"])  # registry's version, not caller's

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
