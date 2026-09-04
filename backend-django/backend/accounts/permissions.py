from rest_framework.permissions import BasePermission

from accounts.models import Operator


class IsAdmin(BasePermission):
    """role == admin - is_staff/is_superuser'dan bağımsız, PDKS'e özgü rol alanı."""
    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and user.role == Operator.ROLE_ADMIN)
