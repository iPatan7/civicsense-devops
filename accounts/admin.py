from django.contrib import admin

from .models import Profile


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "role", "phone", "ward", "department", "is_verified")
    list_filter = ("role", "ward", "department", "is_verified")
    search_fields = ("user__username", "user__email", "phone")
    autocomplete_fields = ("user",)
