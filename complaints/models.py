"""
Database model of the Civic Complaint Intelligence Platform.

Nine tables:

    Department  - who owns the work (Public Works, Water Board, ...)
    Ward        - the municipal area a complaint belongs to
    Category    - the service type, its severity and its SLA
    Complaint   - the complaint itself plus everything the NLP engine decided
    Attachment  - photographs uploaded by the citizen
    Update      - the audit trail of every status change
    Support     - "I have the same problem" from another citizen
    Feedback    - the citizen's rating after the work is done
    TrainingSample - officer corrections that retrain the classifier
"""
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.models import User
from django.core.validators import FileExtensionValidator
from django.db import models
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone


# --------------------------------------------------------------------------
# Reference tables
# --------------------------------------------------------------------------
class Department(models.Model):
    name = models.CharField(max_length=80, unique=True)
    code = models.CharField(max_length=12, unique=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=15, blank=True)
    head_name = models.CharField(max_length=80, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Ward(models.Model):
    name = models.CharField(max_length=80)
    code = models.CharField(max_length=12, unique=True)
    zone = models.CharField(max_length=40, blank=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    population = models.PositiveIntegerField(default=0)
    councillor = models.CharField(max_length=80, blank=True)

    class Meta:
        ordering = ["code"]

    def __str__(self):
        return "%s - %s" % (self.code, self.name)


class Category(models.Model):
    """A service type.  `code` is the label the NLP classifier predicts."""
    name = models.CharField(max_length=80, unique=True)
    code = models.CharField(max_length=20, unique=True)
    department = models.ForeignKey(Department, on_delete=models.PROTECT,
                                   related_name="categories")
    description = models.CharField(max_length=200, blank=True)
    # 0.0 = cosmetic request, 1.0 = life threatening service
    severity = models.FloatField(default=0.5)
    sla_hours = models.PositiveIntegerField(default=72)
    icon = models.CharField(max_length=40, default="bi-exclamation-circle")
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "categories"

    def __str__(self):
        return self.name


# --------------------------------------------------------------------------
# The complaint
# --------------------------------------------------------------------------
class Status(models.TextChoices):
    NEW = "NEW", "Submitted"
    TRIAGED = "TRIAGED", "Triaged"
    ASSIGNED = "ASSIGNED", "Assigned"
    IN_PROGRESS = "IN_PROGRESS", "In progress"
    RESOLVED = "RESOLVED", "Resolved"
    CLOSED = "CLOSED", "Closed"
    REJECTED = "REJECTED", "Rejected"
    DUPLICATE = "DUPLICATE", "Merged as duplicate"


OPEN_STATUSES = (Status.NEW, Status.TRIAGED, Status.ASSIGNED, Status.IN_PROGRESS)


class Priority(models.TextChoices):
    LOW = "LOW", "Low"
    MEDIUM = "MEDIUM", "Medium"
    HIGH = "HIGH", "High"
    CRITICAL = "CRITICAL", "Critical"


class Source(models.TextChoices):
    WEB = "WEB", "Web portal"
    MOBILE = "MOBILE", "Mobile app"
    PHONE = "PHONE", "Call centre"
    WALK_IN = "WALK_IN", "Walk-in counter"


class ComplaintQuerySet(models.QuerySet):
    def open(self):
        return self.filter(status__in=OPEN_STATUSES)

    def overdue(self):
        return self.open().filter(due_at__lt=timezone.now())

    def for_user(self, user):
        """Citizens see their own complaints, staff see their department's."""
        profile = getattr(user, "profile", None)
        if user.is_superuser or (profile and profile.role in ("ADMIN", "OFFICER")):
            return self
        if profile and profile.role == "STAFF" and profile.department_id:
            return self.filter(department_id=profile.department_id)
        return self.filter(citizen=user)

    def duplicates_of(self, complaint):
        return self.filter(duplicate_of=complaint)


class Complaint(models.Model):
    tracking_id = models.CharField(max_length=20, unique=True, db_index=True)
    citizen = models.ForeignKey(User, on_delete=models.CASCADE,
                                related_name="complaints")
    title = models.CharField(max_length=150)
    description = models.TextField()

    # --- where -------------------------------------------------------------
    ward = models.ForeignKey(Ward, null=True, blank=True, on_delete=models.SET_NULL,
                             related_name="complaints")
    address = models.CharField(max_length=250, blank=True)
    landmark = models.CharField(max_length=120, blank=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)

    # --- routing -----------------------------------------------------------
    category = models.ForeignKey(Category, null=True, blank=True,
                                 on_delete=models.SET_NULL, related_name="complaints")
    department = models.ForeignKey(Department, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="complaints")
    assigned_to = models.ForeignKey(User, null=True, blank=True,
                                    on_delete=models.SET_NULL,
                                    related_name="assigned_complaints")

    # --- what the NLP engine decided ---------------------------------------
    ai_category_code = models.CharField(max_length=20, blank=True)
    ai_confidence = models.FloatField(default=0.0)
    ai_keywords = models.JSONField(default=list, blank=True)
    sentiment_label = models.CharField(max_length=10, blank=True)
    sentiment_polarity = models.FloatField(default=0.0)
    urgency_score = models.FloatField(default=0.0)
    priority_score = models.FloatField(default=0.0)
    priority_breakdown = models.JSONField(default=dict, blank=True)
    priority_reasons = models.JSONField(default=list, blank=True)
    is_auto_categorised = models.BooleanField(default=True)
    category_corrected = models.BooleanField(default=False)

    # --- duplicates --------------------------------------------------------
    duplicate_of = models.ForeignKey("self", null=True, blank=True,
                                     on_delete=models.SET_NULL,
                                     related_name="duplicate_children")
    duplicate_score = models.FloatField(default=0.0)
    support_count = models.PositiveIntegerField(default=0)

    # --- workflow ----------------------------------------------------------
    status = models.CharField(max_length=12, choices=Status.choices,
                              default=Status.NEW, db_index=True)
    priority = models.CharField(max_length=8, choices=Priority.choices,
                                default=Priority.MEDIUM, db_index=True)
    source = models.CharField(max_length=8, choices=Source.choices, default=Source.WEB)

    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    due_at = models.DateTimeField(null=True, blank=True, db_index=True)
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    resolution_note = models.TextField(blank=True)
    reopen_count = models.PositiveIntegerField(default=0)

    objects = ComplaintQuerySet.as_manager()

    class Meta:
        ordering = ["-priority_score", "-created_at"]
        indexes = [
            models.Index(fields=["status", "priority"]),
            models.Index(fields=["ward", "status"]),
            models.Index(fields=["category", "status"]),
            models.Index(fields=["created_at"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(priority_score__gte=0) & Q(priority_score__lte=100),
                name="priority_score_between_0_and_100",
            ),
        ]

    def __str__(self):
        return "%s - %s" % (self.tracking_id, self.title)

    def get_absolute_url(self):
        return reverse("complaints:detail", args=[self.tracking_id])

    # -- derived values used all over the dashboard -------------------------
    @property
    def text(self):
        """Title + description: what the NLP engine actually reads."""
        return "%s. %s" % (self.title, self.description)

    @property
    def is_open(self):
        return self.status in OPEN_STATUSES

    @property
    def age_hours(self):
        return (timezone.now() - self.created_at).total_seconds() / 3600.0

    @property
    def age_days(self):
        return self.age_hours / 24.0

    @property
    def sla_hours(self):
        if self.due_at:
            return (self.due_at - self.created_at).total_seconds() / 3600.0
        return self.category.sla_hours if self.category else 72.0

    @property
    def sla_fraction_used(self):
        end = self.resolved_at or timezone.now()
        used = (end - self.created_at).total_seconds() / 3600.0
        return min(used / max(self.sla_hours, 1.0), 2.0)

    @property
    def is_overdue(self):
        if not self.due_at or not self.is_open:
            return False
        return timezone.now() > self.due_at

    @property
    def hours_remaining(self):
        if not self.due_at:
            return None
        return round((self.due_at - timezone.now()).total_seconds() / 3600.0, 1)

    @property
    def resolution_hours(self):
        if not self.resolved_at:
            return None
        return round((self.resolved_at - self.created_at).total_seconds() / 3600.0, 1)

    @property
    def sla_state(self):
        """'breached' / 'due-soon' / 'on-track' - drives the colour in the UI."""
        if not self.is_open or not self.due_at:
            return "closed" if not self.is_open else "on-track"
        if self.is_overdue:
            return "breached"
        warn = getattr(settings, "CIVIC", {}).get("SLA_WARNING_RATIO", 0.75)
        return "due-soon" if self.sla_fraction_used >= warn else "on-track"

    @property
    def priority_rank(self):
        return {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}.get(self.priority, 4)

    def set_due_date(self, sla_hours=None):
        hours = sla_hours or (self.category.sla_hours if self.category else 72)
        self.due_at = self.created_at + timedelta(hours=hours)
        return self.due_at


class Attachment(models.Model):
    complaint = models.ForeignKey(Complaint, on_delete=models.CASCADE,
                                  related_name="attachments")
    # FileField + an extension check is used instead of ImageField so that the
    # project runs without the Pillow library being installed.
    image = models.FileField(
        upload_to="complaints/%Y/%m/",
        validators=[FileExtensionValidator(["jpg", "jpeg", "png", "webp", "gif"])],
    )
    caption = models.CharField(max_length=120, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return "Photo of %s" % self.complaint.tracking_id


class ComplaintUpdate(models.Model):
    """One row per action taken on a complaint: the audit trail."""
    complaint = models.ForeignKey(Complaint, on_delete=models.CASCADE,
                                  related_name="updates")
    actor = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL,
                              related_name="complaint_updates")
    from_status = models.CharField(max_length=12, blank=True)
    to_status = models.CharField(max_length=12, blank=True)
    note = models.TextField(blank=True)
    is_public = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return "%s: %s -> %s" % (self.complaint.tracking_id, self.from_status,
                                 self.to_status)


class Support(models.Model):
    """Another citizen confirming the same problem instead of filing again."""
    complaint = models.ForeignKey(Complaint, on_delete=models.CASCADE,
                                  related_name="supports")
    user = models.ForeignKey(User, on_delete=models.CASCADE,
                             related_name="supported_complaints")
    comment = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["complaint", "user"],
                                    name="one_support_per_citizen"),
        ]

    def __str__(self):
        return "%s supports %s" % (self.user, self.complaint.tracking_id)


class Feedback(models.Model):
    complaint = models.OneToOneField(Complaint, on_delete=models.CASCADE,
                                     related_name="feedback")
    rating = models.PositiveSmallIntegerField()      # 1 - 5 stars
    comment = models.TextField(blank=True)
    sentiment_label = models.CharField(max_length=10, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return "%s rated %d" % (self.complaint.tracking_id, self.rating)


class TrainingSample(models.Model):
    """Officer corrections; the classifier is retrained from these rows.

    This closes the loop: whenever a human changes the predicted category, the
    text and the correct label are stored here, so the same mistake is less
    likely the next time.
    """
    class SampleSource(models.TextChoices):
        CORRECTION = "CORRECTION", "Officer correction"
        CONFIRMED = "CONFIRMED", "Officer confirmation"
        SEED = "SEED", "Seed corpus"

    text = models.TextField()
    category_code = models.CharField(max_length=20, db_index=True)
    source = models.CharField(max_length=12, choices=SampleSource.choices,
                              default=SampleSource.CORRECTION)
    complaint = models.ForeignKey(Complaint, null=True, blank=True,
                                  on_delete=models.SET_NULL,
                                  related_name="training_samples")
    created_by = models.ForeignKey(User, null=True, blank=True,
                                   on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return "%s <- %s" % (self.category_code, self.text[:40])
