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
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import AuditLog
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
