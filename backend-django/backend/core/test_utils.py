"""Ortak base - IsAuthenticated global olduğu için her test bir Operator gerektirir.
force_authenticate() gerçek JWT üretmez; JWT'nin kendisi accounts/tests.py'de test edilir."""
from rest_framework.test import APITestCase

from accounts.models import Operator


class AuthenticatedAPITestCase(APITestCase):
    """Alt sınıflar kendi setUp()'ında en başta super().setUp() çağırmalı."""

    def setUp(self):
        super().setUp()
        self.operator = Operator.objects.create_user(
            username="test-operator", password="irrelevant-not-checked-here",
        )
        self.client.force_authenticate(user=self.operator)
