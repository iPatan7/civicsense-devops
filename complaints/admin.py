from django.contrib import admin
from django.utils.html import format_html

from .models import (Attachment, Category, Complaint, ComplaintUpdate,
                     Department, Feedback, Support, TrainingSample, Ward)


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "head_name", "email", "is_active")
    search_fields = ("name", "code")


@admin.register(Ward)
class WardAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "zone", "councillor", "population")
    search_fields = ("name", "code", "zone")


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "department", "severity", "sla_hours", "is_active")
    list_filter = ("department", "is_active")
    search_fields = ("name", "code")


class UpdateInline(admin.TabularInline):
    model = ComplaintUpdate
    extra = 0
    readonly_fields = ("created_at",)


class AttachmentInline(admin.TabularInline):
    model = Attachment
    extra = 0


@admin.register(Complaint)
class ComplaintAdmin(admin.ModelAdmin):
    list_display = ("tracking_id", "title", "category", "priority_badge", "status",
                    "support_count", "due_at", "created_at")
    list_filter = ("status", "priority", "category", "ward", "department",
                   "is_auto_categorised", "category_corrected")
    search_fields = ("tracking_id", "title", "description", "address")
    readonly_fields = ("tracking_id", "ai_category_code", "ai_confidence",
                       "ai_keywords", "sentiment_label", "sentiment_polarity",
                       "urgency_score", "priority_score", "priority_breakdown",
                       "priority_reasons", "created_at", "updated_at")
    inlines = [UpdateInline, AttachmentInline]
    date_hierarchy = "created_at"

    @admin.display(description="Priority")
    def priority_badge(self, obj):
        colours = {"CRITICAL": "#b3261e", "HIGH": "#c25e00",
                   "MEDIUM": "#1a73e8", "LOW": "#5f6368"}
        return format_html('<b style="color:{}">{} ({})</b>',
                           colours.get(obj.priority, "#000"), obj.priority,
                           round(obj.priority_score))


@admin.register(TrainingSample)
class TrainingSampleAdmin(admin.ModelAdmin):
    list_display = ("category_code", "source", "created_by", "created_at")
    list_filter = ("category_code", "source")
    search_fields = ("text",)


admin.site.register([Support, Feedback])
admin.site.site_header = "CivicSense administration"
admin.site.site_title = "CivicSense"
admin.site.index_title = "Civic Complaint Intelligence Platform"
