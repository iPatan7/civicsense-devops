"""Citizen facing views: file, track, support and follow a complaint."""
import json

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from . import services
from .forms import ComplaintForm, FeedbackForm, SupportForm, TrackForm
from .models import (Category, Complaint, Department, OPEN_STATUSES, Status,
                     Support, Ward)


def healthz(request):
    """Liveness probe for Docker / Kubernetes.

    It also says which release is answering (set by the deployment), so a smoke
    test can check that a blue-green switch really put the new version live.
    """
    return JsonResponse({"status": "ok",
                         "release": settings.CIVIC_RELEASE,
                         "slot": settings.CIVIC_SLOT})


def home(request):
    complaints = Complaint.objects.exclude(status=Status.DUPLICATE)
    context = {
        "metrics": services.dashboard_metrics(),
        "categories": Category.objects.filter(is_active=True)
                              .annotate(total=Count("complaints"))[:10],
        "recent": complaints.order_by("-created_at")[:6],
        "top_priority": complaints.open().order_by("-priority_score")[:5],
        "track_form": TrackForm(),
        "departments": Department.objects.filter(is_active=True).count(),
        "wards": Ward.objects.count(),
    }
    return render(request, "complaints/home.html", context)


@login_required
def file_complaint(request):
    """The core citizen flow: submit -> classified, de-duplicated, prioritised."""
    form = ComplaintForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        complaint, matches = services.file_complaint(
            request.user, form.cleaned_data, source="WEB")

        for uploaded in request.FILES.getlist("photos")[:4]:
            complaint.attachments.create(image=uploaded)

        if complaint.status == Status.DUPLICATE and complaint.duplicate_of:
            messages.warning(
                request,
                "This looks like the same problem as %s, which is already with "
                "the %s department. Your report has been added to it as a "
                "supporting report, so it now carries more weight." % (
                    complaint.duplicate_of.tracking_id,
                    complaint.duplicate_of.department.name
                    if complaint.duplicate_of.department else "concerned"))
        else:
            messages.success(
                request,
                "Complaint %s registered and sent to %s. Expected resolution "
                "by %s." % (complaint.tracking_id,
                            complaint.department.name if complaint.department
                            else "the concerned department",
                            complaint.due_at.strftime("%d %b %Y, %I:%M %p")
                            if complaint.due_at else "the SLA date"))
        return redirect(complaint.get_absolute_url())

    profile = getattr(request.user, "profile", None)
    if profile and profile.ward_id and not form.is_bound:
        form.fields["ward"].initial = profile.ward_id
    return render(request, "complaints/file.html",
                  {"form": form, "categories": Category.objects.filter(is_active=True)})


@login_required
def my_complaints(request):
    queryset = (Complaint.objects.filter(citizen=request.user)
                .select_related("category", "department", "ward", "duplicate_of")
                .order_by("-created_at"))
    status = request.GET.get("status")
    if status == "open":
        queryset = queryset.filter(status__in=OPEN_STATUSES)
    elif status:
        queryset = queryset.filter(status=status)

    supported = (Complaint.objects.filter(supports__user=request.user)
                 .exclude(citizen=request.user).select_related("category")[:10])
    page = Paginator(queryset, 10).get_page(request.GET.get("page"))
    return render(request, "complaints/my_complaints.html",
                  {"page_obj": page, "supported": supported,
                   "status": status or "", "statuses": Status.choices})


def complaint_detail(request, tracking_id):
    complaint = get_object_or_404(
        Complaint.objects.select_related("category", "department", "ward",
                                         "citizen", "assigned_to", "duplicate_of"),
        tracking_id=tracking_id.upper())

    duplicates = complaint.duplicate_children.select_related("citizen")
    has_supported = (request.user.is_authenticated and
                     Support.objects.filter(complaint=complaint,
                                            user=request.user).exists())
    is_owner = request.user == complaint.citizen
    profile = getattr(request.user, "profile", None)

    context = {
        "complaint": complaint,
        "updates": complaint.updates.select_related("actor").filter(is_public=True),
        "duplicates": duplicates,
        "supports": complaint.supports.select_related("user")[:20],
        "has_supported": has_supported,
        "is_owner": is_owner,
        "support_form": SupportForm(),
        "feedback_form": FeedbackForm(instance=getattr(complaint, "feedback", None)),
        "can_review": is_owner and complaint.status in (Status.RESOLVED, Status.CLOSED),
        "is_authority": bool(profile and profile.is_authority),
    }
    return render(request, "complaints/detail.html", context)


def track(request):
    """Public tracking - no login needed, only the tracking id."""
    form = TrackForm(request.GET or None)
    if form.is_valid():
        tracking_id = form.cleaned_data["tracking_id"]
        if Complaint.objects.filter(tracking_id=tracking_id).exists():
            return redirect("complaints:detail", tracking_id=tracking_id)
        messages.error(request, "No complaint found with id %s." % tracking_id)
    return render(request, "complaints/track.html", {"form": form})


def browse(request):
    """Open complaints of the city, so citizens can support instead of repeat."""
    queryset = (Complaint.objects.exclude(status=Status.DUPLICATE)
                .select_related("category", "ward", "department")
                .order_by("-priority_score", "-created_at"))
    ward = request.GET.get("ward")
    category = request.GET.get("category")
    query = request.GET.get("q", "").strip()
    only_open = request.GET.get("open", "1") == "1"

    if ward:
        queryset = queryset.filter(ward__code=ward)
    if category:
        queryset = queryset.filter(category__code=category)
    if only_open:
        queryset = queryset.filter(status__in=OPEN_STATUSES)
    if query:
        queryset = queryset.filter(Q(title__icontains=query) |
                                   Q(description__icontains=query) |
                                   Q(address__icontains=query))

    page = Paginator(queryset, 12).get_page(request.GET.get("page"))
    return render(request, "complaints/browse.html", {
        "page_obj": page,
        "wards": Ward.objects.all(),
        "categories": Category.objects.filter(is_active=True),
        "selected": {"ward": ward or "", "category": category or "",
                     "q": query, "open": only_open},
    })


@login_required
@require_POST
def support_complaint(request, tracking_id):
    complaint = get_object_or_404(Complaint, tracking_id=tracking_id.upper())
    if complaint.citizen_id == request.user.id:
        messages.info(request, "This is your own complaint.")
        return redirect(complaint.get_absolute_url())

    form = SupportForm(request.POST)
    comment = form.cleaned_data.get("comment", "") if form.is_valid() else ""
    _, created = services.add_support(complaint, request.user, comment)
    messages.success(request, "Thank you. Your confirmation was added and the "
                              "priority of this complaint has been recalculated."
                     if created else "You had already confirmed this complaint.")
    return redirect(complaint.get_absolute_url())


@login_required
@require_POST
def give_feedback(request, tracking_id):
    complaint = get_object_or_404(Complaint, tracking_id=tracking_id.upper(),
                                  citizen=request.user)
    form = FeedbackForm(request.POST)
    if form.is_valid():
        services.record_feedback(complaint, form.cleaned_data["rating"],
                                 form.cleaned_data.get("comment", ""))
        messages.success(request, "Thank you for rating the service.")
    else:
        messages.error(request, "Please select a rating between 1 and 5.")
    return redirect(complaint.get_absolute_url())


# --------------------------------------------------------------------------
# JSON endpoints used by the "live assistant" on the complaint form
# --------------------------------------------------------------------------
@login_required
@require_POST
def api_analyse(request):
    """Live preview: category, priority and possible duplicates while typing."""
    try:
        payload = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "invalid json"}, status=400)

    text = ("%s. %s" % (payload.get("title", ""), payload.get("description", ""))).strip()
    if len(text) < 25:
        return JsonResponse({"ready": False})

    ward = Ward.objects.filter(pk=payload.get("ward") or 0).first()
    result = services.analyse(text)
    category = result["category"]

    matches = services.find_duplicates(
        text,
        latitude=payload.get("latitude") or None,
        longitude=payload.get("longitude") or None,
        ward=ward,
        category_code=category.code if category else None,
        limit=3,
    )

    return JsonResponse({
        "ready": True,
        "category": {
            "code": category.code if category else None,
            "name": category.name if category else "Not sure yet",
            "department": category.department.name if category else "",
            "confidence": round(result["classification"]["confidence"] * 100),
            "keywords": result["classification"]["keywords"],
        },
        "priority": {
            "label": result["priority"]["priority"],
            "score": result["priority"]["score"],
            "reasons": result["priority"]["reasons"],
            "sla_hours": result["priority"]["sla_hours"],
        },
        "sentiment": result["sentiment"]["label"],
        "similar": [{
            "tracking_id": complaint.tracking_id,
            "title": complaint.title,
            "status": complaint.get_status_display(),
            "url": complaint.get_absolute_url(),
            "supports": complaint.support_count,
            "similarity": round(match["text_similarity"] * 100),
            "score": round(match["score"] * 100),
            "distance_m": match["distance_m"],
            "is_duplicate": match["is_duplicate"],
        } for complaint, match in matches],
    })
