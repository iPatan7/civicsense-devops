"""Access control for the authority side of the platform."""
from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied


def _profile(user):
    return getattr(user, "profile", None)


def authority_required(view):
    """Only municipal staff, ward officers and administrators."""
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        profile = _profile(request.user)
        if request.user.is_superuser or (profile and profile.is_authority):
            return view(request, *args, **kwargs)
        raise PermissionDenied("This area is for municipal officials only.")
    return wrapper


def officer_required(view):
    """Actions that change ownership: assign, merge, reclassify."""
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        profile = _profile(request.user)
        if request.user.is_superuser or (profile and profile.can_assign):
            return view(request, *args, **kwargs)
        raise PermissionDenied("Only a ward officer or an administrator can do this.")
    return wrapper
