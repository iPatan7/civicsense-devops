"""Template values shared by every page."""
from django.conf import settings


def release(request):
    # Which build and blue-green slot rendered the page; shown in the footer.
    return {"civic_release": settings.CIVIC_RELEASE, "civic_slot": settings.CIVIC_SLOT}
