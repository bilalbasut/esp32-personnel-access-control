"""Card onboarding/assign/revoke, plus created_by/updated_by/deleted_by attribution.
publish_acl_update() is mocked everywhere - no broker under manage.py test."""
from unittest.mock import patch

from django.test import TestCase
from rest_framework import status

from accounts.models import AuditLog
from cards.models import Card, Employee
from core.test_utils import AuthenticatedAPITestCase


class CardOnboardTests(AuthenticatedAPITestCase):
    def setUp(self):
        super().setUp()
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
        self.assertEqual(Employee.objects.count(), employees_before)  # pre-check must run before employee is created
        self.mock_publish.assert_not_called()

    def test_onboard_missing_required_field_returns_400(self):
        response = self.client.post("/api/cards/add", {"full_name": "No UID"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class CardAssignTests(AuthenticatedAPITestCase):
    def setUp(self):
        super().setUp()
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


class CardRevokeTests(AuthenticatedAPITestCase):
    def setUp(self):
        super().setUp()
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


class CardCreateAndSoftDeleteTests(AuthenticatedAPITestCase):
    def setUp(self):
        super().setUp()
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


class EmployeeSoftDeleteTests(AuthenticatedAPITestCase):
    def test_delete_soft_deletes_and_hides_from_list(self):
        employee = Employee.objects.create(full_name="Katherine Johnson")

        response = self.client.delete(f"/api/employees/{employee.id}")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        list_response = self.client.get("/api/employees")
        names = [e["full_name"] for e in list_response.data]
        self.assertNotIn("Katherine Johnson", names)

        preserved = Employee.all_objects.get(id=employee.id)
        self.assertIsNotNone(preserved.deleted_at)
        self.assertEqual(preserved.deleted_by_id, self.operator.id)


class EmployeeAttributionTests(AuthenticatedAPITestCase):
    """No custom perform_*() here - confirms AuditedModelViewSet works stand-alone."""

    def test_create_sets_created_by_and_writes_audit_log(self):
        response = self.client.post(
            "/api/employees", {"full_name": "Hedy Lamarr", "department": "R&D"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)

        employee = Employee.objects.get(full_name="Hedy Lamarr")
        self.assertEqual(employee.created_by_id, self.operator.id)

        entry = AuditLog.objects.get(action="employee.create")
        self.assertEqual(entry.operator_id, self.operator.id)
        self.assertEqual(entry.details["changes"]["full_name"]["new"], "Hedy Lamarr")

    def test_update_sets_updated_by_and_logs_only_the_changed_field(self):
        employee = Employee.objects.create(full_name="Grace Hopper", department="Navy")

        response = self.client.patch(
            f"/api/employees/{employee.id}", {"department": "Engineering"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)

        employee.refresh_from_db()
        self.assertEqual(employee.department, "Engineering")
        self.assertEqual(employee.updated_by_id, self.operator.id)
        self.assertIsNone(employee.created_by_id)  # created directly via ORM, not through the API

        entry = AuditLog.objects.get(action="employee.update")
        self.assertEqual(
            entry.details["changes"], {"department": {"old": "Navy", "new": "Engineering"}}
        )
        self.assertNotIn("full_name", entry.details["changes"])


class CardAttributionTests(AuthenticatedAPITestCase):
    """Confirms the ACL-publish override still calls super() and keeps attribution."""

    def setUp(self):
        super().setUp()
        patcher = patch("cards.views.publish_acl_update")
        self.mock_publish = patcher.start()
        self.addCleanup(patcher.stop)

    def test_create_sets_created_by(self):
        response = self.client.post("/api/cards", {"uid": "ATTR0001"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)

        card = Card.objects.get(uid="ATTR0001")
        self.assertEqual(card.created_by_id, self.operator.id)
        self.assertTrue(AuditLog.objects.filter(action="card.create").exists())

    def test_update_sets_updated_by_and_logs_the_diff(self):
        card = Card.objects.create(uid="ATTR0002", floors="1", is_active=True)

        response = self.client.patch(f"/api/cards/{card.uid}", {"floors": "1,2"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)

        card.refresh_from_db()
        self.assertEqual(card.updated_by_id, self.operator.id)

        entry = AuditLog.objects.get(action="card.update")
        self.assertEqual(entry.details["changes"]["floors"], {"old": "1", "new": "1,2"})

    def test_delete_sets_deleted_by(self):
        card = Card.objects.create(uid="ATTR0003", is_active=True)

        response = self.client.delete(f"/api/cards/{card.uid}")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        preserved = Card.all_objects.get(uid="ATTR0003")
        self.assertEqual(preserved.deleted_by_id, self.operator.id)
        self.assertTrue(AuditLog.objects.filter(action="card.delete").exists())


class CardValidationTests(AuthenticatedAPITestCase):
    """floors: ints 0-31 (relay bit mask). win_start_m/win_end_m: ascending pair, 0-1440."""

    def setUp(self):
        super().setUp()
        patcher = patch("cards.views.publish_acl_update")
        self.mock_publish = patcher.start()
        self.addCleanup(patcher.stop)

    def test_floor_above_31_returns_400(self):
        response = self.client.post("/api/cards", {"uid": "VALID001", "floors": "1,32"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(Card.objects.filter(uid="VALID001").exists())

    def test_negative_floor_returns_400(self):
        response = self.client.post("/api/cards", {"uid": "VALID002", "floors": "-1"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_win_start_not_before_win_end_returns_400(self):
        response = self.client.post(
            "/api/cards", {"uid": "VALID003", "win_start_m": 900, "win_end_m": 800}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_win_end_beyond_one_day_returns_400(self):
        response = self.client.post(
            "/api/cards", {"uid": "VALID004", "win_start_m": 0, "win_end_m": 1500}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_valid_floors_and_window_are_accepted(self):
        response = self.client.post(
            "/api/cards",
            {"uid": "VALID005", "floors": "0,15,31", "win_start_m": 480, "win_end_m": 1020},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        card = Card.objects.get(uid="VALID005")
        self.assertEqual(card.win_start_m, 480)
        self.assertEqual(card.win_end_m, 1020)

    def test_uid_is_stripped_and_uppercased(self):
        # plain POST /api/cards normalizes uid separately from onboard()/revoke()'s own strip/upper.
        response = self.client.post("/api/cards", {"uid": "  ab:cd:ef  "}, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertTrue(Card.objects.filter(uid="AB:CD:EF").exists())
        self.assertFalse(Card.objects.filter(uid="  ab:cd:ef  ").exists())


class EmployeeUniqueConstraintTests(AuthenticatedAPITestCase):
    """Duplicate employee_no must 409, not 500 or a bare 400 from DRF's auto UniqueValidator."""

    def test_duplicate_employee_no_on_create_returns_409_not_500(self):
        Employee.objects.create(full_name="First Person", employee_no="EMP-100")

        response = self.client.post(
            "/api/employees", {"full_name": "Second Person", "employee_no": "EMP-100"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT, response.data)
        self.assertEqual(Employee.objects.filter(employee_no="EMP-100").count(), 1)

    def test_duplicate_employee_no_on_update_returns_409_not_500(self):
        Employee.objects.create(full_name="First Person", employee_no="EMP-200")
        second = Employee.objects.create(full_name="Second Person", employee_no="EMP-201")

        response = self.client.patch(
            f"/api/employees/{second.id}", {"employee_no": "EMP-200"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT, response.data)
        second.refresh_from_db()
        self.assertEqual(second.employee_no, "EMP-201")  # untouched by the failed update

    def test_multiple_employees_with_no_employee_no_are_allowed(self):
        # unique=True allows any number of NULLs in Postgres - only duplicate values collide.
        response1 = self.client.post("/api/employees", {"full_name": "No Badge One"}, format="json")
        response2 = self.client.post("/api/employees", {"full_name": "No Badge Two"}, format="json")
        self.assertEqual(response1.status_code, status.HTTP_201_CREATED, response1.data)
        self.assertEqual(response2.status_code, status.HTTP_201_CREATED, response2.data)


class SoftDeleteBehaviorTests(TestCase):
    """ORM-level, no HTTP - pins down BaseModel's soft-delete guarantees."""

    def test_restore_clears_deleted_at_and_reappears_in_default_manager(self):
        employee = Employee.objects.create(full_name="Restorable Person")
        employee.delete()
        self.assertFalse(Employee.objects.filter(id=employee.id).exists())  # ActiveManager hides it

        employee.restore()
        self.assertTrue(Employee.objects.filter(id=employee.id).exists())
        self.assertIsNone(Employee.objects.get(id=employee.id).deleted_at)

    def test_is_deleted_property_reflects_deleted_at(self):
        employee = Employee.objects.create(full_name="Property Check")
        self.assertFalse(employee.is_deleted)

        employee.delete()
        self.assertTrue(employee.is_deleted)  # same in-memory instance, no refresh needed

        employee.restore()
        self.assertFalse(employee.is_deleted)

    def test_hard_deleting_employee_nulls_a_soft_deleted_cards_employee_fk(self):
        """base_manager_name="all_objects" - else SET_NULL's cascade can't see an already-soft-deleted Card."""
        employee = Employee.objects.create(full_name="Ada Lovelace")
        card = Card.objects.create(uid="HARDDEL01", employee=employee, is_active=True)

        card.delete()  # soft-delete the card FIRST
        self.assertIsNotNone(Card.all_objects.get(uid="HARDDEL01").deleted_at)

        employee.hard_delete()  # a REAL DELETE FROM employees, not soft-delete

        preserved_card = Card.all_objects.get(uid="HARDDEL01")
        self.assertIsNone(preserved_card.employee_id)
