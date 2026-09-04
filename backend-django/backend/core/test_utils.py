"""Ortak test altyapısı - DEFAULT_PERMISSION_CLASSES=[IsAuthenticated]
(config/settings.py) artık login/refresh/logout ve firmware indirme
dışındaki HER endpoint'i kilitliyor, yani gerçek URL routing'e istek atan
her APITestCase'in bir Operator ile authenticate olması gerekiyor - bunu
her test dosyasında tekrar tekrar yazmak yerine tek bir base class.

force_authenticate() DRF test client'ına özel: gerçek bir JWT üretip
Authorization header'ına koymadan, request.user'ı doğrudan set ediyor -
JWT'nin kendisinin (login/refresh/logout) uçtan uca doğru çalıştığını
ayrıca kanıtlaması gereken tek yer accounts/tests.py.
"""
from rest_framework.test import APITestCase

from accounts.models import Operator


class AuthenticatedAPITestCase(APITestCase):
    """Alt sınıfların kendi setUp()'ı varsa EN BAŞTA super().setUp()
    çağırması gerekiyor - aksi halde self.operator/self.client
    authentication'ı hiç kurulmaz."""

    def setUp(self):
        super().setUp()
        self.operator = Operator.objects.create_user(
            username="test-operator", password="irrelevant-not-checked-here",
        )
        self.client.force_authenticate(user=self.operator)
