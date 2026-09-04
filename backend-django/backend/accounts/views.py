from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.serializers import OperatorSerializer


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
