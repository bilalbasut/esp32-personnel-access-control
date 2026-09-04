from rest_framework import status, viewsets
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import Operator
from accounts.permissions import IsAdmin
from accounts.serializers import OperatorCreateSerializer, OperatorSerializer
from core.audit_viewset import AuditedModelViewSet


class MeView(APIView):
    """Access token'ın kime ait olduğunu döner - frontend `role`'e göre admin-only UI gösterir/gizler."""
    def get(self, request):
        if not request.user or not request.user.is_authenticated:
            return Response({"error": "Not authenticated."}, status=status.HTTP_401_UNAUTHORIZED)
        return Response(OperatorSerializer(request.user).data)


class LogoutView(APIView):
    """Access token stateless, silinemez - logout sadece refresh token'ı blacklist'e ekler.
    AllowAny bilerek: access token'ı çoktan süresi dolmuş kullanıcı da logout edebilmeli."""
    permission_classes = [AllowAny]

    def post(self, request):
        refresh = request.data.get("refresh")
        if not refresh:
            return Response({"error": "refresh is required."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            RefreshToken(refresh).blacklist()
        except TokenError:
            pass  # zaten geçersiz/blacklist'te - amaç zaten buydu, başarı dön
        return Response({"message": "Logged out."})


class OperatorViewSet(AuditedModelViewSet, viewsets.ModelViewSet):
    """Operatör hesabı listeleme/oluşturma - admin-only. Edit/delete yok (henüz istenmedi)."""
    queryset = Operator.objects.all().order_by("username")
    permission_classes = [IsAdmin]
    audit_label = "operator"
    http_method_names = ["get", "post", "head", "options"]

    def get_serializer_class(self):
        return OperatorCreateSerializer if self.action == "create" else OperatorSerializer
