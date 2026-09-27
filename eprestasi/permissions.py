"""
Versi DRF dari decorator role_required yang lama.
Pemakaian di view:

    from .permissions import HasRole

    class ContohView(APIView):
        permission_classes = [HasRole.for_roles('siswa', 'admin')]
"""
from rest_framework.permissions import BasePermission


class HasRole(BasePermission):
    allowed_roles = ()

    def has_permission(self, request, view):
        user = request.user
        return bool(user and getattr(user, 'role', None) in self.allowed_roles)

    @classmethod
    def for_roles(cls, *roles):
        return type('HasRoleDynamic', (cls,), {'allowed_roles': roles})
