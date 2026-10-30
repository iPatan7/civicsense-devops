"""User profiles and roles.

Django's own `User` model is kept (it already handles passwords, sessions and
permissions safely) and one extra row per user carries the civic information:
which role the person has, which ward they live in and, for an employee, which
department they work for.
"""
from django.contrib.auth.models import User
from django.db import models


class Role(models.TextChoices):
    CITIZEN = "CITIZEN", "Citizen"
    STAFF = "STAFF", "Department staff"
    OFFICER = "OFFICER", "Ward officer"
    ADMIN = "ADMIN", "Municipal administrator"


class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.CITIZEN)
    phone = models.CharField(max_length=15, blank=True)
    address = models.CharField(max_length=200, blank=True)
    ward = models.ForeignKey("complaints.Ward", null=True, blank=True,
                             on_delete=models.SET_NULL, related_name="residents")
    department = models.ForeignKey("complaints.Department", null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="employees")
    is_verified = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["role"])]

    def __str__(self):
        return "%s (%s)" % (self.user.get_username(), self.get_role_display())

    # -- convenience flags used by the templates and the view decorators ---
    @property
    def is_authority(self):
        return self.role in (Role.STAFF, Role.OFFICER, Role.ADMIN)

    @property
    def is_admin(self):
        return self.role == Role.ADMIN or self.user.is_superuser

    @property
    def can_assign(self):
        return self.role in (Role.OFFICER, Role.ADMIN) or self.user.is_superuser
