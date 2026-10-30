"""Adds the role flags to every template, so the navbar can be built once."""
from .models import Profile, Role


def role_flags(request):
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return {"is_authority": False, "is_admin": False, "profile": None}
    profile = Profile.objects.filter(user=user).select_related("department", "ward").first()
    if profile is None:
        profile = Profile.objects.create(
            user=user, role=Role.ADMIN if user.is_superuser else Role.CITIZEN
        )
    return {
        "profile": profile,
        "is_authority": profile.is_authority or user.is_superuser,
        "is_admin": profile.is_admin,
    }
