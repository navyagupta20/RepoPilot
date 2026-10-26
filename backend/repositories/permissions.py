from rest_framework.permissions import BasePermission


class IsOwner(BasePermission):
    """Object-level check: the object must belong to the requesting user.

    Views ALSO filter their querysets by owner, so another user's object returns 404
    (it does not even reveal that the ID exists). This class is the second safety net.
    """

    def has_object_permission(self, request, view, obj):
        return getattr(obj, "owner_id", None) == request.user.id
