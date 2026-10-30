"""
The intelligence layer: everything the platform decides about a complaint.

The views stay thin - they only collect the form data and render templates -
while all the rules live here, so the same logic serves the web pages, the
JSON API and the management commands.

    file_complaint()      citizen submits  -> classify, detect duplicates,
                                              score priority, set the SLA clock
    change_status()       officer acts     -> audit trail + SLA stamps
    correct_category()    officer fixes    -> new training sample, model retrained
    add_support()         "me too"         -> priority recomputed upwards
"""
import logging
import random
import string
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Avg, Count, F, Q
from django.utils import timezone

from nlpengine import analyse_complaint, find_similar, invalidate as invalidate_model

from .models import (Category, Complaint, ComplaintUpdate, Department,
                     Feedback, OPEN_STATUSES, Priority, Status, Support,
                     TrainingSample)

log = logging.getLogger(__name__)
CONFIG = getattr(settings, "CIVIC", {})


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def generate_tracking_id():
    """CIV-2026-7KQ4X2 - short enough to read out on the phone."""
    year = timezone.now().year
    alphabet = string.ascii_uppercase + string.digits
    for _ in range(20):
        suffix = "".join(random.choices(alphabet, k=6))
        tracking_id = "CIV-%d-%s" % (year, suffix)
        if not Complaint.objects.filter(tracking_id=tracking_id).exists():
            return tracking_id
    raise RuntimeError("Could not generate a unique tracking id")


def training_samples():
    """Officer-labelled complaints that are added to the seed corpus."""
    return list(
        TrainingSample.objects.values_list("text", "category_code")
    )


def category_for_code(code):
    if not code:
        return None
    return Category.objects.filter(code=code, is_active=True).first()


# --------------------------------------------------------------------------
# 1. Automatic categorisation + priority
# --------------------------------------------------------------------------
def analyse(text, category_severity=None, supporters=0, sla_fraction_used=0.0):
    """Run the NLP pipeline on raw text and resolve the predicted Category."""
    result = analyse_complaint(
        text,
        category_severity=0.5 if category_severity is None else category_severity,
        supporters=supporters,
        sla_fraction_used=sla_fraction_used,
        extra_samples=training_samples(),
    )
    predicted = category_for_code(result["classification"]["category"])

    # The severity of the predicted category changes the priority, so the
    # score is computed a second time once the category is known.
    if predicted and category_severity is None:
        result = analyse_complaint(
            text,
            category_severity=predicted.severity,
            supporters=supporters,
            sla_fraction_used=sla_fraction_used,
            extra_samples=training_samples(),
        )
    result["category"] = predicted
    return result


def apply_analysis(complaint, result, keep_category=False):
    """Copy the engine's decision onto the complaint object (not saved yet)."""
    classification = result["classification"]
    priority = result["priority"]

    if not keep_category and result.get("category"):
        confident = classification["confidence"] >= CONFIG.get(
            "CLASSIFIER_MIN_CONFIDENCE", 0.35)
        complaint.category = result["category"]
        complaint.department = result["category"].department
        complaint.is_auto_categorised = True
        complaint.status = Status.TRIAGED if confident else Status.NEW

    complaint.ai_category_code = classification["category"] or ""
    complaint.ai_confidence = classification["confidence"]
    complaint.ai_keywords = classification["keywords"]
    complaint.sentiment_label = result["sentiment"]["label"]
    complaint.sentiment_polarity = result["sentiment"]["polarity"]
    complaint.urgency_score = result["urgency"]["urgency"]
    complaint.priority_score = priority["score"]
    complaint.priority = priority["priority"]
    complaint.priority_breakdown = priority["parts"]
    complaint.priority_reasons = priority["reasons"]

    # The SLA clock is the stricter of the category SLA and the priority SLA:
    # a "low severity" category reported as an emergency still gets a fast SLA.
    category_sla = complaint.category.sla_hours if complaint.category else 72
    complaint.set_due_date(min(category_sla, priority["sla_hours"]))
    return complaint


# --------------------------------------------------------------------------
# 2. Duplicate detection
# --------------------------------------------------------------------------
def duplicate_candidates(ward=None, exclude_id=None, window_days=None):
    """Open complaints that are recent enough to be the same event."""
    window = window_days or CONFIG.get("DUPLICATE_WINDOW_DAYS", 30)
    since = timezone.now() - timedelta(days=window)
    queryset = (Complaint.objects
                .filter(created_at__gte=since)
                .filter(Q(status__in=OPEN_STATUSES) | Q(status=Status.RESOLVED))
                .filter(duplicate_of__isnull=True)
                .select_related("category", "ward"))
    if exclude_id:
        queryset = queryset.exclude(pk=exclude_id)
    if ward is not None:
        # Same ward first, but neighbouring wards are still checked because a
        # pothole can sit exactly on a ward boundary.
        queryset = queryset.filter(Q(ward=ward) | Q(ward__isnull=True) |
                                   Q(ward__zone=getattr(ward, "zone", "")))
    return queryset.order_by("-created_at")[:400]


def find_duplicates(text, latitude=None, longitude=None, ward=None,
                    category_code=None, exclude_id=None, limit=5):
    """Return [(Complaint, match dict)] ranked by similarity."""
    candidates = list(duplicate_candidates(ward=ward, exclude_id=exclude_id))
    if not candidates:
        return []

    payload = [{
        "id": c.pk,
        "text": c.text,
        "latitude": c.latitude,
        "longitude": c.longitude,
        "ward": c.ward_id,
        "age_days": c.age_days,
        "category": c.category.code if c.category else None,
    } for c in candidates]

    matches = find_similar(
        text, payload,
        latitude=latitude, longitude=longitude,
        ward=getattr(ward, "pk", ward),
        category=category_code,
        threshold=CONFIG.get("DUPLICATE_SIMILARITY_THRESHOLD", 0.62),
        radius_m=CONFIG.get("DUPLICATE_RADIUS_METRES", 300),
        window_days=CONFIG.get("DUPLICATE_WINDOW_DAYS", 30),
        limit=limit,
    )
    by_id = {c.pk: c for c in candidates}
    return [(by_id[m["id"]], m) for m in matches if m["id"] in by_id]


# --------------------------------------------------------------------------
# 3. Filing a complaint
# --------------------------------------------------------------------------
@transaction.atomic
def file_complaint(citizen, data, source="WEB", auto_merge=True):
    """Create a complaint and run the whole intelligence pipeline on it.

    Returns (complaint, duplicate_matches).  When the top match is above the
    threshold the new complaint is stored as a DUPLICATE of the original and
    the original's support count goes up, which is what removes the double
    work from the department's queue.
    """
    complaint = Complaint(
        tracking_id=generate_tracking_id(),
        citizen=citizen,
        title=data["title"].strip(),
        description=data["description"].strip(),
        ward=data.get("ward"),
        address=data.get("address", ""),
        landmark=data.get("landmark", ""),
        latitude=data.get("latitude"),
        longitude=data.get("longitude"),
        source=source,
        created_at=timezone.now(),
    )

    result = analyse(complaint.text)
    apply_analysis(complaint, result)

    # A citizen may insist on a category; respect it but remember the model's
    # opinion for the accuracy report.
    chosen = data.get("category")
    if chosen:
        complaint.category = chosen
        complaint.department = chosen.department
        complaint.is_auto_categorised = False
        complaint.set_due_date(min(chosen.sla_hours, result["priority"]["sla_hours"]))

    complaint.save()

    matches = find_duplicates(
        complaint.text,
        latitude=complaint.latitude, longitude=complaint.longitude,
        ward=complaint.ward,
        category_code=complaint.category.code if complaint.category else None,
        exclude_id=complaint.pk,
    )

    top = matches[0] if matches else None
    if auto_merge and top and top[1]["is_duplicate"]:
        merge_as_duplicate(complaint, top[0], top[1]["score"], actor=citizen,
                           automatic=True)
    else:
        log_update(complaint, actor=citizen, to_status=complaint.status,
                   note="Complaint registered. Auto-categorised as %s "
                        "(confidence %.0f%%), priority %s (score %.0f)." % (
                            complaint.category.name if complaint.category else "unclassified",
                            complaint.ai_confidence * 100,
                            complaint.priority, complaint.priority_score))
    return complaint, matches


# --------------------------------------------------------------------------
# 4. Workflow actions
# --------------------------------------------------------------------------
def log_update(complaint, actor=None, from_status="", to_status="", note="",
               is_public=True):
    return ComplaintUpdate.objects.create(
        complaint=complaint, actor=actor, from_status=from_status,
        to_status=to_status, note=note, is_public=is_public)


@transaction.atomic
def merge_as_duplicate(child, parent, score, actor=None, automatic=False):
    """Point `child` at `parent` and move its supporters across."""
    if parent.duplicate_of_id:            # never build a chain of duplicates
        parent = parent.duplicate_of
    if parent.pk == child.pk:
        return child

    child.duplicate_of = parent
    child.duplicate_score = score
    child.status = Status.DUPLICATE
    child.save(update_fields=["duplicate_of", "duplicate_score", "status",
                              "updated_at"])

    Support.objects.get_or_create(complaint=parent, user=child.citizen,
                                  defaults={"comment": child.title[:200]})
    refresh_support_count(parent)
    recompute_priority(parent)

    how = "automatically" if automatic else "by %s" % (actor or "an officer")
    log_update(child, actor=actor, to_status=Status.DUPLICATE,
               note="Merged %s into %s (similarity %.0f%%)." % (
                   how, parent.tracking_id, score * 100))
    log_update(parent, actor=actor, to_status=parent.status,
               note="%s was reported again (%s); support count is now %d." % (
                   parent.tracking_id, child.tracking_id, parent.support_count))
    return child


@transaction.atomic
def unmerge(child, actor=None):
    """An officer decides the two complaints are actually different."""
    parent = child.duplicate_of
    child.duplicate_of = None
    child.duplicate_score = 0.0
    child.status = Status.TRIAGED
    child.save(update_fields=["duplicate_of", "duplicate_score", "status",
                              "updated_at"])
    if parent:
        Support.objects.filter(complaint=parent, user=child.citizen).delete()
        refresh_support_count(parent)
        recompute_priority(parent)
        log_update(child, actor=actor, to_status=child.status,
                   note="Separated from %s: it is a different issue." % parent.tracking_id)
    return child


def refresh_support_count(complaint):
    complaint.support_count = complaint.supports.count()
    complaint.save(update_fields=["support_count", "updated_at"])
    return complaint.support_count


def recompute_priority(complaint, save=True):
    """Re-score a complaint as it ages and as more citizens report it."""
    result = analyse(
        complaint.text,
        category_severity=complaint.category.severity if complaint.category else 0.5,
        supporters=complaint.support_count,
        sla_fraction_used=complaint.sla_fraction_used,
    )
    priority = result["priority"]
    complaint.priority_score = priority["score"]
    complaint.priority = priority["priority"]
    complaint.priority_breakdown = priority["parts"]
    complaint.priority_reasons = priority["reasons"]
    if save:
        complaint.save(update_fields=["priority_score", "priority",
                                      "priority_breakdown", "priority_reasons",
                                      "updated_at"])
    return complaint


@transaction.atomic
def add_support(complaint, user, comment=""):
    """'I have the same problem' - the strongest signal a queue can get."""
    target = complaint.duplicate_of or complaint
    support, created = Support.objects.get_or_create(
        complaint=target, user=user, defaults={"comment": comment[:200]})
    if created:
        refresh_support_count(target)
        recompute_priority(target)
        log_update(target, actor=user, to_status=target.status,
                   note="Another citizen confirmed this problem (%d in total)."
                        % target.support_count)
    return support, created


@transaction.atomic
def change_status(complaint, new_status, actor=None, note=""):
    """Move a complaint through the workflow and keep the SLA stamps right."""
    old_status = complaint.status
    if old_status == new_status and not note:
        return complaint

    complaint.status = new_status
    now = timezone.now()
    fields = ["status", "updated_at"]

    if not complaint.acknowledged_at and new_status in (
            Status.TRIAGED, Status.ASSIGNED, Status.IN_PROGRESS):
        complaint.acknowledged_at = now
        fields.append("acknowledged_at")
    if new_status == Status.RESOLVED:
        complaint.resolved_at = now
        complaint.resolution_note = note or complaint.resolution_note
        fields += ["resolved_at", "resolution_note"]
    if new_status == Status.CLOSED:
        complaint.closed_at = now
        complaint.resolved_at = complaint.resolved_at or now
        fields += ["closed_at", "resolved_at"]
    if old_status in (Status.RESOLVED, Status.CLOSED) and new_status in OPEN_STATUSES:
        complaint.reopen_count = F("reopen_count") + 1
        complaint.resolved_at = None
        complaint.closed_at = None
        fields += ["reopen_count", "resolved_at", "closed_at"]

    complaint.save(update_fields=fields)
    complaint.refresh_from_db()
    log_update(complaint, actor=actor, from_status=old_status,
               to_status=new_status, note=note)
    return complaint


@transaction.atomic
def assign(complaint, staff_user, actor=None, note=""):
    complaint.assigned_to = staff_user
    profile = getattr(staff_user, "profile", None)
    if profile and profile.department_id:
        complaint.department_id = profile.department_id
    complaint.save(update_fields=["assigned_to", "department", "updated_at"])
    if complaint.status in (Status.NEW, Status.TRIAGED):
        change_status(complaint, Status.ASSIGNED, actor=actor,
                      note=note or "Assigned to %s." % staff_user.get_username())
    else:
        log_update(complaint, actor=actor, to_status=complaint.status,
                   note=note or "Assigned to %s." % staff_user.get_username())
    return complaint


@transaction.atomic
def correct_category(complaint, category, actor=None):
    """An officer fixes the predicted category -> the model learns from it.

    This is the active-learning loop of the platform: the correction is stored
    as a labelled training sample and the in-memory classifier is dropped, so
    the very next complaint is classified by a model that has seen this fix.
    """
    was = complaint.category
    complaint.category = category
    complaint.department = category.department
    complaint.category_corrected = was is not None and was.pk != category.pk
    complaint.is_auto_categorised = False
    complaint.save(update_fields=["category", "department", "category_corrected",
                                  "is_auto_categorised", "updated_at"])

    TrainingSample.objects.create(
        text=complaint.text,
        category_code=category.code,
        source=TrainingSample.SampleSource.CORRECTION if complaint.category_corrected
        else TrainingSample.SampleSource.CONFIRMED,
        complaint=complaint,
        created_by=actor,
    )
    invalidate_model()          # force a retrain on the next classification
    recompute_priority(complaint)
    log_update(complaint, actor=actor, to_status=complaint.status,
               note="Category set to %s (was %s). The classifier has been "
                    "retrained with this example." % (
                        category.name, was.name if was else "unclassified"))
    return complaint


@transaction.atomic
def record_feedback(complaint, rating, comment=""):
    from nlpengine import analyse_sentiment
    feedback, _ = Feedback.objects.update_or_create(
        complaint=complaint,
        defaults={"rating": rating, "comment": comment,
                  "sentiment_label": analyse_sentiment(comment)["label"] if comment else ""},
    )
    if complaint.status == Status.RESOLVED and rating >= 3:
        change_status(complaint, Status.CLOSED, actor=complaint.citizen,
                      note="Citizen rated the resolution %d/5." % rating)
    elif rating <= 2:
        change_status(complaint, Status.IN_PROGRESS, actor=complaint.citizen,
                      note="Citizen was not satisfied (%d/5); reopened." % rating)
    return feedback


# --------------------------------------------------------------------------
# 5. Numbers for the authority dashboard
# --------------------------------------------------------------------------
def dashboard_metrics(queryset=None):
    queryset = Complaint.objects.all() if queryset is None else queryset
    total = queryset.count()
    open_qs = queryset.filter(status__in=OPEN_STATUSES)
    resolved = queryset.filter(status__in=[Status.RESOLVED, Status.CLOSED])
    duplicates = queryset.filter(status=Status.DUPLICATE).count()

    resolution_hours = [c.resolution_hours for c in
                        resolved.exclude(resolved_at__isnull=True)[:500]]
    average_hours = (sum(resolution_hours) / len(resolution_hours)
                     if resolution_hours else 0.0)

    return {
        "total": total,
        "open": open_qs.count(),
        "overdue": open_qs.filter(due_at__lt=timezone.now()).count(),
        "critical": open_qs.filter(priority=Priority.CRITICAL).count(),
        "resolved": resolved.count(),
        "duplicates": duplicates,
        "duplicate_rate": round(duplicates * 100.0 / total, 1) if total else 0.0,
        "resolution_rate": round(resolved.count() * 100.0 / total, 1) if total else 0.0,
        "avg_resolution_hours": round(average_hours, 1),
        "avg_rating": round(
            Feedback.objects.filter(complaint__in=queryset)
            .aggregate(a=Avg("rating"))["a"] or 0.0, 2),
        "auto_classified": queryset.filter(is_auto_categorised=True).count(),
        "corrections": queryset.filter(category_corrected=True).count(),
    }


def classifier_accuracy():
    """How often did the officer keep the predicted category?"""
    reviewed = Complaint.objects.filter(
        Q(category_corrected=True) | Q(training_samples__isnull=False)
    ).distinct().count()
    wrong = Complaint.objects.filter(category_corrected=True).count()
    if not reviewed:
        return None
    return round((reviewed - wrong) * 100.0 / reviewed, 1)


def chart_data(queryset=None, days=14):
    """Everything the dashboard charts need, in one query set of aggregates."""
    queryset = Complaint.objects.all() if queryset is None else queryset
    since = timezone.now() - timedelta(days=days)

    by_category = list(
        queryset.exclude(category__isnull=True)
        .values("category__name")
        .annotate(count=Count("id"))
        .order_by("-count")[:10]
    )
    by_status = list(queryset.values("status").annotate(count=Count("id")))
    by_priority = list(queryset.values("priority").annotate(count=Count("id")))
    by_ward = list(
        queryset.exclude(ward__isnull=True)
        .values("ward__name", "ward__code")
        .annotate(count=Count("id"),
                  overdue=Count("id", filter=Q(status__in=OPEN_STATUSES,
                                               due_at__lt=timezone.now())))
        .order_by("-count")[:10]
    )

    trend_map = {}
    for row in (queryset.filter(created_at__gte=since)
                .values("created_at__date")
                .annotate(count=Count("id"))):
        trend_map[row["created_at__date"]] = row["count"]
    today = timezone.now().date()
    trend = [{"date": (today - timedelta(days=offset)).isoformat(),
              "count": trend_map.get(today - timedelta(days=offset), 0)}
             for offset in range(days - 1, -1, -1)]

    return {
        "by_category": by_category,
        "by_status": by_status,
        "by_priority": by_priority,
        "by_ward": by_ward,
        "trend": trend,
    }


def sla_report():
    """Per-department SLA performance, used by the reports page."""
    rows = []
    for department in Department.objects.filter(is_active=True):
        complaints = Complaint.objects.filter(department=department)
        total = complaints.count()
        if not total:
            continue
        closed = complaints.filter(status__in=[Status.RESOLVED, Status.CLOSED])
        in_time = sum(1 for c in closed if c.resolved_at and c.due_at
                      and c.resolved_at <= c.due_at)
        rows.append({
            "department": department.name,
            "total": total,
            "open": complaints.filter(status__in=OPEN_STATUSES).count(),
            "overdue": complaints.filter(status__in=OPEN_STATUSES,
                                         due_at__lt=timezone.now()).count(),
            "resolved": closed.count(),
            "sla_met": in_time,
            "sla_percent": round(in_time * 100.0 / closed.count(), 1) if closed.count() else 0.0,
        })
    return sorted(rows, key=lambda r: r["sla_percent"])
