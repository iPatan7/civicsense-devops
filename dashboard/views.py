"""
The authority dashboard: one screen per job an official actually does.

    index      - is the city on track today?
    queue      - what should my crew attend first?
    detail     - act on one complaint (assign, update, resolve, reclassify)
    duplicates - confirm or reject the merges the engine proposed
    reports    - SLA performance, ward hot-spots and classifier accuracy
"""
import json

from django.contrib import messages
from django.contrib.auth.models import User
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.models import Role
from complaints import services
from complaints.forms import StatusUpdateForm
from complaints.models import (Category, Complaint, Department, OPEN_STATUSES,
                               Priority, Status, Ward)

from .decorators import authority_required, officer_required


def _scope(request):
    """Staff only see their own department; officers see everything."""
    return Complaint.objects.for_user(request.user)


@authority_required
def index(request):
    queryset = _scope(request)
    charts = services.chart_data(queryset)
    open_queryset = queryset.filter(status__in=OPEN_STATUSES)

    context = {
        "metrics": services.dashboard_metrics(queryset),
        "accuracy": services.classifier_accuracy(),
        "critical": open_queryset.filter(priority=Priority.CRITICAL)
                                 .select_related("category", "ward")[:6],
        "overdue": open_queryset.filter(due_at__lt=timezone.now())
                                .select_related("category", "ward")
                                .order_by("due_at")[:6],
        "unassigned": open_queryset.filter(assigned_to__isnull=True).count(),
        "pending_duplicates": queryset.filter(status=Status.DUPLICATE,
                                              duplicate_of__isnull=False).count(),
        "charts_json": json.dumps(charts),
        "wards": charts["by_ward"],
        "recent": queryset.exclude(status=Status.DUPLICATE)
                          .select_related("category", "citizen")
                          .order_by("-created_at")[:8],
    }
    return render(request, "dashboard/index.html", context)


@authority_required
def queue(request):
    queryset = (_scope(request)
                .select_related("category", "ward", "department", "assigned_to",
                                "citizen")
                .exclude(status=Status.DUPLICATE))

    filters = {
        "status": request.GET.get("status", ""),
        "priority": request.GET.get("priority", ""),
        "category": request.GET.get("category", ""),
        "ward": request.GET.get("ward", ""),
        "department": request.GET.get("department", ""),
        "sla": request.GET.get("sla", ""),
        "q": request.GET.get("q", "").strip(),
        "sort": request.GET.get("sort", "priority"),
    }

    if filters["status"] == "open":
        queryset = queryset.filter(status__in=OPEN_STATUSES)
    elif filters["status"]:
        queryset = queryset.filter(status=filters["status"])
    if filters["priority"]:
        queryset = queryset.filter(priority=filters["priority"])
    if filters["category"]:
        queryset = queryset.filter(category__code=filters["category"])
    if filters["ward"]:
        queryset = queryset.filter(ward__code=filters["ward"])
    if filters["department"]:
        queryset = queryset.filter(department__code=filters["department"])
    if filters["sla"] == "breached":
        queryset = queryset.filter(status__in=OPEN_STATUSES,
                                   due_at__lt=timezone.now())
    elif filters["sla"] == "unassigned":
        queryset = queryset.filter(assigned_to__isnull=True,
                                   status__in=OPEN_STATUSES)
    if filters["q"]:
        queryset = queryset.filter(Q(tracking_id__icontains=filters["q"]) |
                                   Q(title__icontains=filters["q"]) |
                                   Q(description__icontains=filters["q"]) |
                                   Q(address__icontains=filters["q"]))

    ordering = {
        "priority": ("-priority_score", "-created_at"),
        "oldest": ("created_at",),
        "newest": ("-created_at",),
        "due": ("due_at",),
        "supports": ("-support_count", "-priority_score"),
    }.get(filters["sort"], ("-priority_score",))
    queryset = queryset.order_by(*ordering)

    page = Paginator(queryset, 15).get_page(request.GET.get("page"))
    return render(request, "dashboard/queue.html", {
        "page_obj": page,
        "filters": filters,
        "statuses": Status.choices,
        "priorities": Priority.choices,
        "categories": Category.objects.filter(is_active=True),
        "wards": Ward.objects.all(),
        "departments": Department.objects.filter(is_active=True),
        "staff": _assignable_staff(request.user),
        "total": queryset.count(),
    })


def _assignable_staff(user):
    profile = getattr(user, "profile", None)
    staff = (User.objects.filter(profile__role__in=[Role.STAFF, Role.OFFICER])
             .select_related("profile__department").order_by("username"))
    if profile and profile.role == Role.STAFF and profile.department_id:
        staff = staff.filter(profile__department_id=profile.department_id)
    return staff


@authority_required
def detail(request, tracking_id):
    complaint = get_object_or_404(
        _scope(request).select_related("category", "department", "ward",
                                       "citizen", "assigned_to", "duplicate_of"),
        tracking_id=tracking_id.upper())

    similar = services.find_duplicates(
        complaint.text,
        latitude=complaint.latitude, longitude=complaint.longitude,
        ward=complaint.ward,
        category_code=complaint.category.code if complaint.category else None,
        exclude_id=complaint.pk, limit=4)

    return render(request, "dashboard/detail.html", {
        "complaint": complaint,
        "updates": complaint.updates.select_related("actor"),
        "status_form": StatusUpdateForm(initial={"status": complaint.status}),
        "categories": Category.objects.filter(is_active=True),
        "staff": _assignable_staff(request.user),
        "similar": similar,
        "duplicates": complaint.duplicate_children.select_related("citizen"),
        "supports": complaint.supports.select_related("user")[:20],
    })


@authority_required
@require_POST
def update_status(request, tracking_id):
    complaint = get_object_or_404(_scope(request), tracking_id=tracking_id.upper())
    form = StatusUpdateForm(request.POST)
    if form.is_valid():
        services.change_status(complaint, form.cleaned_data["status"],
                               actor=request.user,
                               note=form.cleaned_data.get("note", ""))
        messages.success(request, "%s moved to %s." % (complaint.tracking_id,
                                                       complaint.get_status_display()))
    else:
        messages.error(request, "Invalid status update.")
    return redirect("dashboard:detail", tracking_id=complaint.tracking_id)


@officer_required
@require_POST
def assign(request, tracking_id):
    complaint = get_object_or_404(_scope(request), tracking_id=tracking_id.upper())
    staff = get_object_or_404(User, pk=request.POST.get("staff"))
    services.assign(complaint, staff, actor=request.user,
                    note=request.POST.get("note", ""))
    messages.success(request, "%s assigned to %s." % (complaint.tracking_id,
                                                      staff.get_username()))
    return redirect("dashboard:detail", tracking_id=complaint.tracking_id)


@officer_required
@require_POST
def reclassify(request, tracking_id):
    """The officer corrects the category; the classifier learns from it."""
    complaint = get_object_or_404(_scope(request), tracking_id=tracking_id.upper())
    category = get_object_or_404(Category, pk=request.POST.get("category"))
    services.correct_category(complaint, category, actor=request.user)
    messages.success(
        request,
        "Category set to %s. This correction has been added to the training "
        "data, so similar complaints will be routed correctly." % category.name)
    return redirect("dashboard:detail", tracking_id=complaint.tracking_id)


@officer_required
@require_POST
def merge(request, tracking_id):
    child = get_object_or_404(_scope(request), tracking_id=tracking_id.upper())
    parent = get_object_or_404(Complaint, tracking_id=request.POST.get("parent", "").upper())
    services.merge_as_duplicate(child, parent, float(request.POST.get("score", 0) or 0),
                                actor=request.user)
    messages.success(request, "%s merged into %s." % (child.tracking_id,
                                                      parent.tracking_id))
    return redirect("dashboard:detail", tracking_id=parent.tracking_id)


@officer_required
@require_POST
def unmerge(request, tracking_id):
    child = get_object_or_404(Complaint, tracking_id=tracking_id.upper())
    services.unmerge(child, actor=request.user)
    messages.success(request, "%s is now a separate complaint again." % child.tracking_id)
    return redirect("dashboard:detail", tracking_id=child.tracking_id)


@authority_required
def duplicates(request):
    """Clusters the engine has built, newest first, for human confirmation."""
    parents = (Complaint.objects.filter(duplicate_children__isnull=False)
               .annotate(children=Count("duplicate_children"))
               .select_related("category", "ward", "department")
               .order_by("-children", "-priority_score").distinct())
    page = Paginator(parents, 10).get_page(request.GET.get("page"))
    clusters = [{
        "parent": parent,
        "children": parent.duplicate_children.select_related("citizen").all(),
    } for parent in page.object_list]

    merged = Complaint.objects.filter(status=Status.DUPLICATE).count()
    total = Complaint.objects.count()
    return render(request, "dashboard/duplicates.html", {
        "clusters": clusters,
        "page_obj": page,
        "merged": merged,
        "saved_percent": round(merged * 100.0 / total, 1) if total else 0.0,
    })


@authority_required
def reports(request):
    queryset = _scope(request)
    charts = services.chart_data(queryset, days=30)
    ward_rows = (queryset.exclude(ward__isnull=True)
                 .values("ward__code", "ward__name")
                 .annotate(total=Count("id"),
                           open=Count("id", filter=Q(status__in=OPEN_STATUSES)),
                           overdue=Count("id", filter=Q(status__in=OPEN_STATUSES,
                                                        due_at__lt=timezone.now())),
                           duplicates=Count("id", filter=Q(status=Status.DUPLICATE)))
                 .order_by("-total"))
    return render(request, "dashboard/reports.html", {
        "metrics": services.dashboard_metrics(queryset),
        "sla_rows": services.sla_report(),
        "ward_rows": ward_rows,
        "accuracy": services.classifier_accuracy(),
        "charts_json": json.dumps(charts),
        "category_rows": (queryset.exclude(category__isnull=True)
                          .values("category__name", "category__code")
                          .annotate(total=Count("id"),
                                    corrected=Count("id", filter=Q(category_corrected=True)))
                          .order_by("-total")),
    })


@authority_required
def api_charts(request):
    """JSON used by the charts, so the dashboard can refresh without a reload."""
    return JsonResponse({
        "metrics": services.dashboard_metrics(_scope(request)),
        "charts": services.chart_data(_scope(request)),
    })
