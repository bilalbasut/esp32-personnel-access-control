from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.serializers import OperatorSerializer


class MeView(APIView):
    """GET /api/auth/me - POST /api/auth/login'den alınan token'ın kime ait
    olduğunu döndürür (obtain_auth_token, DRF'in hazır view'ı, config/urls.py
    içinde bağlanmış). Frontend'in ayrı bir Operator-detail endpoint'ine
    ihtiyaç duymadan kimin giriş yaptığını öğrenip `role`'e göre admin-only
    aksiyonları göster/gizle yapmasını sağlıyor."""
    def get(self, request):
        if not request.user or not request.user.is_authenticated:
            return Response({"error": "Not authenticated."}, status=status.HTTP_401_UNAUTHORIZED)
        return Response(OperatorSerializer(request.user).data)
