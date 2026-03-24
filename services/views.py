from datetime import timedelta, datetime
from decimal import Decimal
import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Sum, Count, Q
from django.shortcuts import redirect, render
from django.utils import timezone

from inventory.models import Branch
from users.utils import role_required

from .forms import ServiceRecordForm
from .models import ServiceRecord


# =========================================================
# HELPERS
# =========================================================
def _role(request):
    try:
        return request.user.profile.role
    except Exception:
        return None


def _is_admin(request):
    return _role(request) == "admin"


def _is_cashier(request):
    return _role(request) == "cashier"


def _is_seller(request):
    return _role(request) == "seller"


def _user_branch(request):
    try:
        return request.user.profile.branch
    except Exception:
        return None


def _allowed_branches(request):
    qs = Branch.objects.filter(is_active=True).order_by("name")
    if _is_seller(request):
        ub = _user_branch(request)
        if ub:
            return qs.filter(pk=ub.pk)
        return qs.none()
    return qs


def _selected_branch(request):
    if _is_seller(request):
        return _user_branch(request)

    branch_id = (request.GET.get("branch") or request.POST.get("branch") or "").strip()
    if not branch_id:
        return None
    return _allowed_branches(request).filter(pk=branch_id).first()


def _services_qs(request):
    qs = ServiceRecord.objects.select_related("branch", "created_by")

    if _is_seller(request):
        ub = _user_branch(request)
        if ub:
            qs = qs.filter(branch=ub)
        else:
            qs = qs.none()

    selected = _selected_branch(request)
    if selected:
        qs = qs.filter(branch=selected)

    return qs


def _parse_date(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except Exception:
        return None


# =========================================================
# DASHBOARD
# =========================================================
@login_required
@role_required(["admin", "cashier", "seller"])
def dashboard(request):
    today = timezone.localdate()
    branches = _allowed_branches(request)
    selected_branch = _selected_branch(request)

    date_from_str = (request.GET.get("date_from") or "").strip()
    date_to_str = (request.GET.get("date_to") or "").strip()

    date_from = _parse_date(date_from_str)
    date_to = _parse_date(date_to_str)

    if not date_from and not date_to:
        date_from = today.replace(day=1)
        date_to = today

    if date_from and not date_to:
        date_to = today
    if date_to and not date_from:
        date_from = date_to

    qs = _services_qs(request)

    filtered_qs = qs
    if date_from:
        filtered_qs = filtered_qs.filter(created_at__date__gte=date_from)
    if date_to:
        filtered_qs = filtered_qs.filter(created_at__date__lte=date_to)

    today_qs = qs.filter(created_at__date=today)
    month_start = today.replace(day=1)
    month_qs = qs.filter(created_at__date__gte=month_start)

    today_total = today_qs.aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
    month_total = month_qs.aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
    period_total = filtered_qs.aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
    overall_total = qs.aggregate(total=Sum("amount"))["total"] or Decimal("0.00")

    today_count = today_qs.count()
    month_count = month_qs.count()
    period_count = filtered_qs.count()
    overall_count = qs.count()

    compressor_total = filtered_qs.filter(
        service_type=ServiceRecord.SERVICE_COMPRESSOR
    ).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")

    welding_total = filtered_qs.filter(
        service_type=ServiceRecord.SERVICE_WELDING
    ).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")

    compressor_count = filtered_qs.filter(
        service_type=ServiceRecord.SERVICE_COMPRESSOR
    ).count()

    welding_count = filtered_qs.filter(
        service_type=ServiceRecord.SERVICE_WELDING
    ).count()

    recent_services = filtered_qs.order_by("-created_at")[:12]

    # last 7 days chart
    chart_labels = []
    chart_values = []
    for i in range(6, -1, -1):
        day = today - timedelta(days=i)
        total = qs.filter(created_at__date=day).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
        chart_labels.append(day.strftime("%d %b"))
        chart_values.append(float(total))

    # service mix chart
    service_mix_labels = ["Compressor Machine", "Welding Machine"]
    service_mix_values = [float(compressor_total), float(welding_total)]

    if date_from and date_to:
        if date_from == date_to:
            range_label = date_from.strftime("%d %b %Y")
        else:
            range_label = f"{date_from.strftime('%d %b %Y')} - {date_to.strftime('%d %b %Y')}"
    else:
        range_label = "All time"

    context = {
        "branches": branches,
        "selected_branch": (selected_branch.pk if selected_branch else ""),
        "selected_branch_obj": selected_branch,
        "date_from": date_from.strftime("%Y-%m-%d") if date_from else "",
        "date_to": date_to.strftime("%Y-%m-%d") if date_to else "",
        "today_str": today.strftime("%Y-%m-%d"),
        "last7_from": (today - timedelta(days=6)).strftime("%Y-%m-%d"),
        "range_label": range_label,

        "today_total": today_total,
        "month_total": month_total,
        "period_total": period_total,
        "overall_total": overall_total,

        "today_count": today_count,
        "month_count": month_count,
        "period_count": period_count,
        "overall_count": overall_count,

        "compressor_total": compressor_total,
        "welding_total": welding_total,
        "compressor_count": compressor_count,
        "welding_count": welding_count,

        "recent_services": recent_services,

        "chart_labels_json": json.dumps(chart_labels),
        "chart_values_json": json.dumps(chart_values),
        "service_mix_labels_json": json.dumps(service_mix_labels),
        "service_mix_values_json": json.dumps(service_mix_values),

        "page_title": "Services Dashboard",
    }
    return render(request, "services/dashboard.html", context)


# =========================================================
# CREATE
# =========================================================
@login_required
@role_required(["admin", "cashier", "seller"])
def service_create(request):
    branches = _allowed_branches(request)
    selected_branch = _selected_branch(request)

    if request.method == "POST":
        form = ServiceRecordForm(request.POST)

        if _is_seller(request):
            ub = _user_branch(request)
            if ub:
                form.fields["branch"].queryset = Branch.objects.filter(pk=ub.pk)
            else:
                form.fields["branch"].queryset = Branch.objects.none()
        else:
            form.fields["branch"].queryset = branches

        if form.is_valid():
            obj = form.save(commit=False)
            obj.created_by = request.user

            if _is_seller(request):
                obj.branch = _user_branch(request)

            if not obj.branch:
                messages.error(request, "Please select branch.")
            else:
                obj.save()
                messages.success(request, "Service saved successfully.")
                return redirect("services:service_list")
    else:
        form = ServiceRecordForm()

        if _is_seller(request):
            ub = _user_branch(request)
            if ub:
                form.fields["branch"].queryset = Branch.objects.filter(pk=ub.pk)
                form.fields["branch"].initial = ub.pk
            else:
                form.fields["branch"].queryset = Branch.objects.none()
        else:
            form.fields["branch"].queryset = branches
            if selected_branch:
                form.fields["branch"].initial = selected_branch.pk

    context = {
        "form": form,
        "branches": branches,
        "selected_branch": selected_branch,
        "page_title": "Add Service",
    }
    return render(request, "services/service_form.html", context)


# =========================================================
# LIST
# =========================================================
@login_required
@role_required(["admin", "cashier", "seller"])
def service_list(request):
    branches = _allowed_branches(request)
    selected_branch = _selected_branch(request)

    q = (request.GET.get("q") or "").strip()
    service_type = (request.GET.get("service_type") or "").strip()

    qs = _services_qs(request)

    if q:
        qs = qs.filter(
            Q(customer_name__icontains=q) |
            Q(customer_phone__icontains=q) |
            Q(notes__icontains=q)
        )

    if service_type:
        qs = qs.filter(service_type=service_type)

    total_amount = qs.aggregate(total=Sum("amount"))["total"] or Decimal("0.00")

    context = {
        "services": qs[:300],
        "branches": branches,
        "selected_branch": selected_branch,
        "query": q,
        "service_type": service_type,
        "service_choices": ServiceRecord.SERVICE_CHOICES,
        "total_amount": total_amount,
        "page_title": "Service List",
    }
    return render(request, "services/service_list.html", context)


# =========================================================
# REPORTS
# =========================================================
from decimal import Decimal
import json
from collections import OrderedDict
from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.db.models import Sum, Count
from django.db.models.functions import TruncDate
from django.shortcuts import render
from django.utils import timezone

from users.utils import role_required
from .models import ServiceRecord


@login_required
@role_required(["admin", "cashier", "seller"])
def reports(request):
    branches = _allowed_branches(request)
    selected_branch = _selected_branch(request)

    date_from = (request.GET.get("date_from") or "").strip()
    date_to = (request.GET.get("date_to") or "").strip()
    service_type = (request.GET.get("service_type") or "").strip()

    qs = _services_qs(request).select_related("branch", "created_by").order_by("-created_at")

    if date_from:
        qs = qs.filter(created_at__date__gte=date_from)
    if date_to:
        qs = qs.filter(created_at__date__lte=date_to)
    if service_type:
        qs = qs.filter(service_type=service_type)

    total_amount = qs.aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
    total_count = qs.aggregate(c=Count("id"))["c"] or 0

    compressor_total = (
        qs.filter(service_type=ServiceRecord.SERVICE_COMPRESSOR)
        .aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
    )
    welding_total = (
        qs.filter(service_type=ServiceRecord.SERVICE_WELDING)
        .aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
    )

    # -------------------------
    # CHART 1: Daily totals
    # -------------------------
    daily_rows = (
        qs.annotate(day=TruncDate("created_at"))
        .values("day")
        .annotate(
            total_amount=Sum("amount"),
            total_count=Count("id"),
        )
        .order_by("day")
    )

    daily_labels = []
    daily_amounts = []
    daily_counts = []

    for row in daily_rows:
        day = row["day"]
        daily_labels.append(day.strftime("%d %b %Y"))
        daily_amounts.append(float(row["total_amount"] or 0))
        daily_counts.append(int(row["total_count"] or 0))

    # -------------------------
    # CHART 2: Service type split
    # -------------------------
    service_type_labels = ["Compressor", "Welding"]
    service_type_amounts = [
        float(compressor_total or 0),
        float(welding_total or 0),
    ]

    service_type_counts = [
        qs.filter(service_type=ServiceRecord.SERVICE_COMPRESSOR).count(),
        qs.filter(service_type=ServiceRecord.SERVICE_WELDING).count(),
    ]

    # -------------------------
    # CHART 3: Branch totals
    # -------------------------
    branch_rows = (
        qs.values("branch__name")
        .annotate(
            total_amount=Sum("amount"),
            total_count=Count("id"),
        )
        .order_by("-total_amount", "branch__name")
    )

    branch_labels = []
    branch_amounts = []
    branch_counts = []

    for row in branch_rows:
        branch_labels.append(row["branch__name"] or "No Branch")
        branch_amounts.append(float(row["total_amount"] or 0))
        branch_counts.append(int(row["total_count"] or 0))

    # -------------------------
    # CHART 4: Last 7 days summary
    # -------------------------
    today = timezone.localdate()
    last_7_days = [today - timedelta(days=i) for i in range(6, -1, -1)]

    last7_map = OrderedDict(
        (d.strftime("%d %b"), {"amount": 0.0, "count": 0}) for d in last_7_days
    )

    last7_rows = (
        qs.filter(created_at__date__gte=last_7_days[0], created_at__date__lte=last_7_days[-1])
        .annotate(day=TruncDate("created_at"))
        .values("day")
        .annotate(
            total_amount=Sum("amount"),
            total_count=Count("id"),
        )
        .order_by("day")
    )

    for row in last7_rows:
        key = row["day"].strftime("%d %b")
        if key in last7_map:
            last7_map[key]["amount"] = float(row["total_amount"] or 0)
            last7_map[key]["count"] = int(row["total_count"] or 0)

    last7_labels = list(last7_map.keys())
    last7_amounts = [v["amount"] for v in last7_map.values()]
    last7_counts = [v["count"] for v in last7_map.values()]

    context = {
        "services": qs[:500],
        "branches": branches,
        "selected_branch": selected_branch,
        "date_from": date_from,
        "date_to": date_to,
        "service_type": service_type,
        "service_choices": ServiceRecord.SERVICE_CHOICES,
        "total_amount": total_amount,
        "total_count": total_count,
        "compressor_total": compressor_total,
        "welding_total": welding_total,
        "page_title": "Service Reports",

        # charts
        "daily_labels_json": json.dumps(daily_labels),
        "daily_amounts_json": json.dumps(daily_amounts),
        "daily_counts_json": json.dumps(daily_counts),

        "service_type_labels_json": json.dumps(service_type_labels),
        "service_type_amounts_json": json.dumps(service_type_amounts),
        "service_type_counts_json": json.dumps(service_type_counts),

        "branch_labels_json": json.dumps(branch_labels),
        "branch_amounts_json": json.dumps(branch_amounts),
        "branch_counts_json": json.dumps(branch_counts),

        "last7_labels_json": json.dumps(last7_labels),
        "last7_amounts_json": json.dumps(last7_amounts),
        "last7_counts_json": json.dumps(last7_counts),
    }
    return render(request, "services/reports.html", context)