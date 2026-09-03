"""Backend test suite - card onboarding/assign/revoke.

These exercise CardViewSet's custom actions (cards/views.py) end-to-end
through the real URL routing, since that's where the riskiest logic lives:
atomic employee+card creation, the duplicate-UID 409 paths (both the
pre-check and the IntegrityError fallback), soft-delete via ActiveManager,
and the "no employee -> inactive by default" rule in CardSerializer.create().

publish_acl_update() is mocked everywhere: it does a real network publish
via paho-mqtt (core/mqtt_utils.py), and there's no broker running under
`manage.py test`. What we care about here is that the view *calls* it after
a successful mutation, not the MQTT wire format (core/acl.py's
build_acl_buffer() would be the place for that, if/when it gets its own
test).
"""
from unittest.mock import patch

from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import AuditLog
from cards.models import Card, Employee


class CardOnboardTests(APITestCase):
    def setUp(self):
        patcher = patch("cards.views.publish_acl_update")
        self.mock_publish = patcher.start()
        self.addCleanup(patcher.stop)

    def test_onboard_creates_employee_and_card_atomically(self):
        response = self.client.post("/api/cards/add", {
            "full_name": "Ada Lovelace",
            "department": "Engineering",
            "uid": "aa:bb:cc:dd",
            "floors": "1,2,3",
        }, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)

        employee = Employee.objects.get(full_name="Ada Lovelace")
        card = Card.objects.get(uid="AA:BB:CC:DD")  # onboard() upper-cases the uid
        self.assertEqual(card.employee_id, employee.id)
        self.assertTrue(card.is_active)
        self.assertEqual(response.data["employee_id"], employee.id)
        self.assertEqual(response.data["uid"], "AA:BB:CC:DD")

        self.assertTrue(AuditLog.objects.filter(action="card.onboard").exists())
        self.mock_publish.assert_called_once()

    def test_onboard_duplicate_uid_returns_409_and_creates_nothing(self):
        Card.objects.create(uid="DEADBEEF", is_active=True)
        employees_before = Employee.objects.count()

        response = self.client.post("/api/cards/add", {
            "full_name": "Grace Hopper",
            "uid": "deadbeef",
        }, format="json")

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        # The pre-check must short-circuit before the employee is created -
        # otherwise a rejected onboard would still leave an orphan Employee row.
        self.assertEqual(Employee.objects.count(), employees_before)
        self.mock_publish.assert_not_called()

    def test_onboard_missing_required_field_returns_400(self):
        response = self.client.post("/api/cards/add", {"full_name": "No UID"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class CardAssignTests(APITestCase):
    def setUp(self):
        patcher = patch("cards.views.publish_acl_update")
        self.mock_publish = patcher.start()
        self.addCleanup(patcher.stop)

        self.employee = Employee.objects.create(full_name="Linus Torvalds")
        self.card = Card.objects.create(uid="CAFEBABE", is_active=False)

    def test_assign_links_employee_and_activates_by_default(self):
        response = self.client.put(
            f"/api/cards/{self.card.uid}/assign",
            {"employee_id": self.employee.id},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)

        self.card.refresh_from_db()
        self.assertEqual(self.card.employee_id, self.employee.id)
        self.assertTrue(self.card.is_active)
        self.mock_publish.assert_called_once()

    def test_assign_null_employee_id_unlinks_and_deactivates(self):
        self.card.employee = self.employee
        self.card.is_active = True
        self.card.save(update_fields=["employee", "is_active"])

        response = self.client.put(
            f"/api/cards/{self.card.uid}/assign",
            {"employee_id": None},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)

        self.card.refresh_from_db()
        self.assertIsNone(self.card.employee_id)
        self.assertFalse(self.card.is_active)

    def test_assign_nonexistent_employee_id_returns_400(self):
        response = self.client.put(
            f"/api/cards/{self.card.uid}/assign",
            {"employee_id": 999999},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.mock_publish.assert_not_called()

    def test_assign_unknown_card_returns_404(self):
        response = self.client.put(
            "/api/cards/DOES-NOT-EXIST/assign",
            {"employee_id": self.employee.id},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class CardRevokeTests(APITestCase):
    def setUp(self):
        patcher = patch("cards.views.publish_acl_update")
        self.mock_publish = patcher.start()
        self.addCleanup(patcher.stop)

    def test_revoke_deactivates_card(self):
        card = Card.objects.create(uid="FEEDFACE", is_active=True)

        response = self.client.post("/api/cards/revoke", {"uid": "feedface"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)

        card.refresh_from_db()
        self.assertFalse(card.is_active)
        self.assertTrue(AuditLog.objects.filter(action="card.revoke").exists())
        self.mock_publish.assert_called_once()

    def test_revoke_missing_uid_returns_400(self):
        response = self.client.post("/api/cards/revoke", {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_revoke_unknown_uid_returns_404(self):
        response = self.client.post("/api/cards/revoke", {"uid": "NOPE"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class CardCreateAndSoftDeleteTests(APITestCase):
    def setUp(self):
        patcher = patch("cards.views.publish_acl_update")
        self.mock_publish = patcher.start()
        self.addCleanup(patcher.stop)

    def test_create_without_employee_defaults_inactive(self):
        response = self.client.post("/api/cards", {"uid": "0102030405"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertFalse(Card.objects.get(uid="0102030405").is_active)

    def test_create_with_employee_stays_active(self):
        employee = Employee.objects.create(full_name="Margaret Hamilton")
        response = self.client.post(
            "/api/cards", {"uid": "0A0B0C0D0E", "employee_id": employee.id}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertTrue(Card.objects.get(uid="0A0B0C0D0E").is_active)

    def test_create_duplicate_uid_returns_409_not_500(self):
        Card.objects.create(uid="ABCDEF01", is_active=True)
        response = self.client.post("/api/cards", {"uid": "abcdef01"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)

    def test_delete_soft_deletes_and_hides_from_default_queryset(self):
        card = Card.objects.create(uid="11223344", is_active=True)

        response = self.client.delete(f"/api/cards/{card.uid}")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        self.assertFalse(Card.objects.filter(uid="11223344").exists())  # ActiveManager
        preserved = Card.all_objects.get(uid="11223344")
        self.assertFalse(preserved.is_active)
        self.assertIsNotNone(preserved.deleted_at)
        self.mock_publish.assert_called_once()


class EmployeeSoftDeleteTests(APITestCase):
    def test_delete_soft_deletes_and_hides_from_list(self):
        employee = Employee.objects.create(full_name="Katherine Johnson")

        response = self.client.delete(f"/api/employees/{employee.id}")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        list_response = self.client.get("/api/employees")
        names = [e["full_name"] for e in list_response.data]
        self.assertNotIn("Katherine Johnson", names)

        preserved = Employee.all_objects.get(id=employee.id)
        self.assertIsNotNone(preserved.deleted_at)
