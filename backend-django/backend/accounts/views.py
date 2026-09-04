from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.serializers import OperatorSerializer


class MeView(APIView):
    """GET /api/auth/me - POST /api/auth/login'den alınan access token'ın
    kime ait olduğunu döndürür (JWTAuthentication, DEFAULT_AUTHENTICATION_
    CLASSES üzerinden otomatik doğruluyor - burada elle token çözmeye gerek
    yok). Frontend'in ayrı bir Operator-detail endpoint'ine ihtiyaç
    duymadan kimin giriş yaptığını öğrenip `role`'e göre admin-only
    aksiyonları göster/gizle yapmasını sağlıyor."""
    def get(self, request):
        if not request.user or not request.user.is_authenticated:
            return Response({"error": "Not authenticated."}, status=status.HTTP_401_UNAUTHORIZED)
        return Response(OperatorSerializer(request.user).data)


class LogoutView(APIView):
    """POST /api/auth/logout - {"refresh": "<refresh_token>"}. Access
    token'ı sunucu tarafında "silmek" mümkün değil (stateless, kısa ömürlü -
    bkz. config/settings.py SIMPLE_JWT yorumu); logout'ta gerçekten
    yapılabilecek olan tek şey refresh token'ı blacklist'e eklemek, ki
    çalınmış/eski bir refresh token bir daha yeni access token üretmek için
    kullanılamasın. permission_classes=[AllowAny] BİLEREK: refresh token
    süresi dolmuş bir kullanıcı da (access token'ı çoktan geçersiz olmuş
    olabilir) logout'u tetikleyebilmeli - IsAuthenticated burada zaten
    kırılgan bir kontrol olurdu."""
    permission_classes = [AllowAny]

    def post(self, request):
        refresh = request.data.get("refresh")
        if not refresh:
            return Response({"error": "refresh is required."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            RefreshToken(refresh).blacklist()
        except TokenError:
            # Zaten geçersiz/blacklist'te/süresi dolmuş bir refresh token -
            # logout'un AMACI zaten "bu token bir daha kullanılamasın", yani
            # sonuç aynı: 400'le uğraştırmak yerine başarı dönüp devam ediyoruz.
            pass
        return Response({"message": "Logged out."})
