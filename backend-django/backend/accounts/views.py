from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.serializers import OperatorSerializer


class MeView(APIView):
    """GET /api/auth/me - identifies the caller of a token obtained from
    POST /api/auth/login (rest_framework.authtoken's built-in
    obtain_auth_token view, wired up in config/urls.py). Lets a frontend
    confirm who's logged in and show/hide admin-only actions by `role`
    without needing a separate Operator-detail endpoint."""
    def get(self, request):
        if not request.user or not request.user.is_authenticated:
            return Response({"error": "Not authenticated."}, status=status.HTTP_401_UNAUTHORIZED)
        return Response(OperatorSerializer(request.user).data)
