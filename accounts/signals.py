"""Every new user automatically gets a profile row."""
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Profile, Role


@receiver(post_save, sender=User)
def create_profile(sender, instance, created, **kwargs):
    if created:
        Profile.objects.create(
            user=instance,
            role=Role.ADMIN if instance.is_superuser else Role.CITIZEN,
        )
