from decimal import Decimal
import json
from datetime import datetime, timedelta, date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.timezone import localdate

from inventory.models import Branch
from sales.views import _get_user_branch, _is_admin, _is_cashier, _is_seller
from users.utils import role_required

from .forms import AgrovetExpenseForm, AgrovetPaymentForm, AgrovetSaleForm
from .models import (
    AgrovetCustomer,
    AgrovetExpense,
    AgrovetPayment,
    AgrovetProduct,
    AgrovetSale,
     dec,
)


# =========================================================
# HELPERS
# =========================================================
def _role_lower(request):
    profile = getattr(request.user, "profile", None)
    return (getattr(profile, "role", "") or "").lower()


def _is_agrovet(request):
    return _role_lower(request) == "agrovet"


def _branches_qs():
    """
    Agrovet-visible branches only.
    Admin/Cashier can choose from these.
    Agrovet/Seller are locked to their own branch.
    """
    return Branch.objects.filter(is_active=True).order_by("name")


def _selected_branch(request):
    """
    Seller => always locked to own branch
    Agrovet => always locked to own branch
    Admin/Cashier => can choose branch from GET or POST
    """
    if _is_seller(request) or _is_agrovet(request):
        return _get_user_branch(request)

    branch_id = (request.GET.get("branch") or request.POST.get("branch") or "").strip()
    if not branch_id:
        return None
    return _branches_qs().filter(pk=branch_id).first()


def _can_choose_branch(request):
    """
    Only admin and cashier can manually change branch filter.
    Agrovet and seller are locked.
    """
    return _is_admin(request) or _is_cashier(request)


def _branch_context(request, branch):
    """
    Branch dropdown should show only for admin/cashier.
    Agrovet and seller should not see all branches.
    """
    return {
        "branches": _branches_qs() if _can_choose_branch(request) else [],
        "selected_branch": str(branch.id) if branch else "",
        "selected_branch_obj": branch,
        "is_seller": _is_seller(request),
        "is_agrovet": _is_agrovet(request),
        "is_admin": _is_admin(request),
        "is_cashier": _is_cashier(request),
    }


def _style_form_fields(form):
    for _, field in form.fields.items():
        widget = field.widget
        current = widget.attrs.get("class", "")

        if widget.__class__.__name__.lower() in ["textarea"]:
            widget.attrs["class"] = f"{current} form-control".strip()
            widget.attrs.setdefault("rows", 3)
        elif widget.__class__.__name__.lower() in ["select", "selectmultiple"]:
            widget.attrs["class"] = f"{current} form-select".strip()
        else:
            widget.attrs["class"] = f"{current} form-control".strip()

    return form


def _save_customer(name="", phone=""):
    """
    Create/update agrovet customer.
    """
    name = (name or "").strip()
    phone = (phone or "").strip()

    if not name and not phone:
        return None

    clean_name = name or "Customer"

    if phone:
        customer = AgrovetCustomer.objects.filter(phone=phone).first()
        if customer:
            weak_names = ["", "customer", "unknown", "walk-in"]
            if clean_name and (customer.name or "").strip().lower() in weak_names:
                customer.name = clean_name
                customer.save(update_fields=["name"])
            return customer

        return AgrovetCustomer.objects.create(
            name=clean_name,
            phone=phone,
        )

    customer = AgrovetCustomer.objects.filter(name__iexact=clean_name).first()
    if customer:
        return customer

    return AgrovetCustomer.objects.create(
        name=clean_name,
        phone="",
    )


def _sale_scope_qs(request):
    """
    Seller => own branch only
    Agrovet => own branch only
    Admin/Cashier => all
    """
    qs = AgrovetSale.objects.select_related("branch", "customer", "created_by", "product")

    if _is_seller(request) or _is_agrovet(request):
        user_branch = _get_user_branch(request)
        if user_branch:
            qs = qs.filter(branch=user_branch)
        else:
            qs = qs.filter(created_by=request.user)

    return qs


def _expense_scope_qs(request):
    """
    Seller => own branch only
    Agrovet => own branch only
    Admin/Cashier => all
    """
    qs = AgrovetExpense.objects.select_related("branch", "created_by")

    if _is_seller(request) or _is_agrovet(request):
        user_branch = _get_user_branch(request)
        if user_branch:
            qs = qs.filter(branch=user_branch)

    return qs


def _product_scope_qs(request):
    """
    Seller => own branch products only
    Agrovet => own branch products only
    Admin/Cashier => all
    """
    qs = AgrovetProduct.objects.filter(is_active=True).select_related("branch")

    if _is_seller(request) or _is_agrovet(request):
        user_branch = _get_user_branch(request)
        if user_branch:
            qs = qs.filter(branch=user_branch)

    return qs


def _must_own_sale_if_locked_user(request, sale):
    """
    Seller/Agrovet can access only own branch sale.
    """
    if not (_is_seller(request) or _is_agrovet(request)):
        return True

    user_branch = _get_user_branch(request)
    if user_branch and sale.branch_id:
        return sale.branch_id == user_branch.id

    return sale.created_by_id == request.user.id


def _parse_dashboard_period(request):
    today = localdate()
    mode = (request.GET.get("mode") or "day").strip().lower()

    date_from_raw = (request.GET.get("date_from") or "").strip()
    date_to_raw = (request.GET.get("date_to") or "").strip()
    month_raw = (request.GET.get("month") or "").strip()
    year_raw = (request.GET.get("year") or "").strip()

    def safe_date(v):
        try:
            return datetime.strptime(v, "%Y-%m-%d").date()
        except Exception:
            return None

    def month_range(y, m):
        start = date(y, m, 1)
        if m == 12:
            end = date(y + 1, 1, 1) - timedelta(days=1)
        else:
            end = date(y, m + 1, 1) - timedelta(days=1)
        return start, end

    if mode == "custom":
        start = safe_date(date_from_raw) or today
        end = safe_date(date_to_raw) or today
        if start > end:
            start, end = end, start
        label = f"{start.strftime('%d %b %Y')} → {end.strftime('%d %b %Y')}"
        return mode, start, end, label

    if mode == "year":
        try:
            year_val = int(year_raw or today.year)
        except Exception:
            year_val = today.year
        start = date(year_val, 1, 1)
        end = date(year_val, 12, 31)
        label = str(year_val)
        return mode, start, end, label

    if mode == "month":
        try:
            month_val = int(month_raw or today.month)
        except Exception:
            month_val = today.month
        try:
            year_val = int(year_raw or today.year)
        except Exception:
            year_val = today.year

        if month_val < 1 or month_val > 12:
            month_val = today.month

        start, end = month_range(year_val, month_val)
        label = start.strftime("%B %Y")
        return mode, start, end, label

    start = today
    end = today
    label = today.strftime("%d %b %Y")
    return "day", start, end, label


# =========================================================
# DASHBOARD
# =========================================================
@login_required
@role_required(["admin", "cashier", "seller", "agrovet"])
def dashboard(request):
    branch = _selected_branch(request)

    sales_qs = _sale_scope_qs(request)
    exp_qs = _expense_scope_qs(request)

    if branch and _can_choose_branch(request):
        sales_qs = sales_qs.filter(branch=branch)
        exp_qs = exp_qs.filter(branch=branch)

    mode, start_date, end_date, range_label = _parse_dashboard_period(request)

    period_sales_qs = sales_qs.filter(
        sold_at__date__range=[start_date, end_date]
    ).order_by("-sold_at", "-id")

    period_expenses_qs = exp_qs.filter(
        date__range=[start_date, end_date]
    ).order_by("-date", "-id")

    total_sales = Decimal("0.00")
    total_profit = Decimal("0.00")
    total_balance = Decimal("0.00")
    total_buying = Decimal("0.00")

    cash_total = Decimal("0.00")
    bank_total = Decimal("0.00")
    mobile_total = Decimal("0.00")
    debt_total = Decimal("0.00")

    for sale in period_sales_qs:
        total_sales += Decimal(sale.total_selling or 0)
        total_profit += Decimal(sale.profit or 0)
        total_balance += Decimal(sale.balance or 0)
        total_buying += Decimal(sale.total_buying or 0)

        method = (sale.payment_method or "").lower()
        if method == "cash":
            cash_total += Decimal(sale.total_selling or 0)
        elif method == "bank":
            bank_total += Decimal(sale.total_selling or 0)
        elif method == "mobile":
            mobile_total += Decimal(sale.total_selling or 0)
        elif method == "debt":
            debt_total += Decimal(sale.total_selling or 0)

    total_expenses = period_expenses_qs.aggregate(t=Sum("amount"))["t"] or Decimal("0.00")
    net = total_profit - Decimal(total_expenses or 0)

    sales_count = period_sales_qs.count()
    expenses_count = period_expenses_qs.count()

    customer_ids = period_sales_qs.exclude(customer__isnull=True).values_list("customer_id", flat=True).distinct()
    customers_count = AgrovetCustomer.objects.filter(id__in=customer_ids).count()

    # -----------------------------
    # Chart 1: trend by selected range
    # -----------------------------
    trend_labels = []
    trend_sales = []
    trend_profit = []
    trend_expenses = []

    cursor = start_date
    while cursor <= end_date:
        day_sales_qs = period_sales_qs.filter(sold_at__date=cursor)
        day_exp_qs = period_expenses_qs.filter(date=cursor)

        day_sales_total = Decimal("0.00")
        day_profit_total = Decimal("0.00")

        for s in day_sales_qs:
            day_sales_total += Decimal(s.total_selling or 0)
            day_profit_total += Decimal(s.profit or 0)

        day_exp_total = day_exp_qs.aggregate(t=Sum("amount"))["t"] or Decimal("0.00")

        trend_labels.append(cursor.strftime("%d %b"))
        trend_sales.append(float(day_sales_total))
        trend_profit.append(float(day_profit_total))
        trend_expenses.append(float(day_exp_total))

        cursor += timedelta(days=1)

    # -----------------------------
    # Chart 2: payment method pie
    # -----------------------------
    payment_labels = ["Cash", "Bank", "Mobile", "Debt"]
    payment_values = [
        float(cash_total),
        float(bank_total),
        float(mobile_total),
        float(debt_total),
    ]

    # -----------------------------
    # Chart 3: category bar chart
    # -----------------------------
    category_map = {}
    for s in period_sales_qs:
        key = (s.category or "Uncategorized").strip() or "Uncategorized"
        category_map.setdefault(key, Decimal("0.00"))
        category_map[key] += Decimal(s.total_selling or 0)

    sorted_categories = sorted(category_map.items(), key=lambda x: x[1], reverse=True)[:8]
    category_labels = [k for k, _ in sorted_categories]
    category_values = [float(v) for _, v in sorted_categories]

    # -----------------------------
    # Chart 4: last 6 months trend
    # -----------------------------
    monthly_labels = []
    monthly_sales = []
    monthly_profit = []

    today = localdate()
    months = []
    y = today.year
    m = today.month

    for offset in range(5, -1, -1):
        mm = m - offset
        yy = y
        while mm <= 0:
            mm += 12
            yy -= 1
        months.append((yy, mm))

    for yy, mm in months:
        month_start = date(yy, mm, 1)
        if mm == 12:
            month_end = date(yy + 1, 1, 1) - timedelta(days=1)
        else:
            month_end = date(yy, mm + 1, 1) - timedelta(days=1)

        m_qs = sales_qs.filter(sold_at__date__range=[month_start, month_end])

        m_sales = Decimal("0.00")
        m_profit = Decimal("0.00")
        for s in m_qs:
            m_sales += Decimal(s.total_selling or 0)
            m_profit += Decimal(s.profit or 0)

        monthly_labels.append(month_start.strftime("%b %Y"))
        monthly_sales.append(float(m_sales))
        monthly_profit.append(float(m_profit))

    context = {
        **_branch_context(request, branch),

        "total_sales": total_sales,
        "total_profit": total_profit,
        "total_expenses": total_expenses,
        "total_balance": total_balance,
        "total_buying": total_buying,
        "net": net,
        "sales_count": sales_count,
        "expenses_count": expenses_count,
        "customers_count": customers_count,

        "range_mode": mode,
        "range_label": range_label,
        "date_from": start_date.isoformat(),
        "date_to": end_date.isoformat(),
        "selected_month": request.GET.get("month", str(today.month)),
        "selected_year": request.GET.get("year", str(today.year)),

        "trend_labels_json": json.dumps(trend_labels),
        "trend_sales_json": json.dumps(trend_sales),
        "trend_profit_json": json.dumps(trend_profit),
        "trend_expenses_json": json.dumps(trend_expenses),

        "payment_labels_json": json.dumps(payment_labels),
        "payment_values_json": json.dumps(payment_values),

        "category_labels_json": json.dumps(category_labels),
        "category_values_json": json.dumps(category_values),

        "monthly_labels_json": json.dumps(monthly_labels),
        "monthly_sales_json": json.dumps(monthly_sales),
        "monthly_profit_json": json.dumps(monthly_profit),
    }
    return render(request, "agrovet/dashboard.html", context)


# =========================================================
# SALES
# =========================================================
@login_required
@role_required(["admin", "cashier", "seller", "agrovet"])
def sale_create(request):
    branch = _selected_branch(request)

    if request.method == "POST":
        post_data = request.POST.copy()
        if _is_seller(request) or _is_agrovet(request):
            locked_branch = _get_user_branch(request)
            if locked_branch and "branch" in post_data:
                post_data["branch"] = str(locked_branch.id)

        form = AgrovetSaleForm(post_data)

        if form.is_valid():
            obj = form.save(commit=False)

            if _is_seller(request) or _is_agrovet(request):
                locked_branch = _get_user_branch(request)
                if locked_branch:
                    obj.branch = locked_branch

            customer_name = (form.cleaned_data.get("customer_name") or "").strip()
            customer_phone = (form.cleaned_data.get("customer_phone") or "").strip()
            customer = _save_customer(customer_name, customer_phone)

            if customer:
                obj.customer = customer

            if obj.payment_method in ["cash", "bank", "mobile"] and Decimal(obj.amount_paid or 0) <= 0:
                obj.amount_paid = obj.total_selling

            obj.created_by = request.user
            obj.save()

            # reload product after stock deduction
            saved_product = None
            if obj.product_id:
                saved_product = AgrovetProduct.objects.filter(pk=obj.product_id).first()

            if saved_product:
                if dec(saved_product.stock_qty) <= 0:
                    messages.warning(
                        request,
                        f"Sale saved successfully. {saved_product.name} is now OUT OF STOCK."
                    )
                elif dec(saved_product.reorder_level) > 0 and dec(saved_product.stock_qty) <= dec(saved_product.reorder_level):
                    messages.warning(
                        request,
                        f"Sale saved successfully. {saved_product.name} is now LOW STOCK ({saved_product.stock_qty} left)."
                    )
                else:
                    messages.success(request, "Agrovet sale recorded successfully.")
            else:
                messages.success(request, "Agrovet sale recorded successfully.")

            return redirect("agrovet:sale_list")

        messages.error(request, "Please fix the errors below.")
    else:
        form = AgrovetSaleForm()
        if _is_seller(request) or _is_agrovet(request):
            locked_branch = _get_user_branch(request)
            if locked_branch and "branch" in form.fields:
                form.fields["branch"].initial = locked_branch
                form.fields["branch"].widget.attrs["disabled"] = True

    form = _style_form_fields(form)

    products_qs = _product_scope_qs(request)
    if branch and _can_choose_branch(request):
        products_qs = products_qs.filter(branch=branch)

    products_data = []
    for p in products_qs.order_by("name", "id"):
        products_data.append({
            "id": p.id,
            "item_name": p.name or "",
            "category": p.category or "",
            "unit": p.unit or "",
            "buying_price": float(p.buying_price or 0),
            "selling_price": float(p.selling_price or 0),
            "stock_qty": float(p.stock_qty or 0),
            "reorder_level": float(p.reorder_level or 0),
            "stock_status": p.stock_status,
            "branch_id": p.branch_id,
            "branch_name": p.branch.name if p.branch else "",
        })

    context = {
        **_branch_context(request, branch),
        "form": form,
        "products_json": json.dumps(products_data),
    }
    return render(request, "agrovet/sale_form.html", context)

@login_required
@role_required(["admin", "cashier", "seller", "agrovet"])
def sale_list(request):
    q = (request.GET.get("q") or "").strip()
    branch = _selected_branch(request)

    qs = _sale_scope_qs(request)

    if branch and _can_choose_branch(request):
        qs = qs.filter(branch=branch)

    if q:
        qs = qs.filter(
            Q(item_name__icontains=q) |
            Q(category__icontains=q) |
            Q(customer__name__icontains=q) |
            Q(customer__phone__icontains=q)
        )

    page_obj = Paginator(qs.order_by("-sold_at", "-id"), 20).get_page(request.GET.get("page", 1))

    context = {
        **_branch_context(request, branch),
        "sales": page_obj.object_list,
        "page_obj": page_obj,
        "query": q,
    }
    return render(request, "agrovet/sale_list.html", context)


@login_required
@role_required(["admin", "cashier", "seller", "agrovet"])
def sale_detail(request, pk):
    sale = get_object_or_404(
        AgrovetSale.objects.select_related("branch", "customer", "created_by", "product"),
        pk=pk
    )

    if not _must_own_sale_if_locked_user(request, sale):
        messages.error(request, "You do not have permission to view this sale.")
        return redirect("agrovet:sale_list")

    payments = sale.payments.order_by("-paid_at", "-id")

    return render(request, "agrovet/sale_detail.html", {
        "sale": sale,
        "payments": payments,
        "balance": sale.balance,
        "total_paid": sale.total_paid,
    })


@login_required
@role_required(["admin", "cashier", "seller", "agrovet"])
def add_payment(request, pk):
    sale = get_object_or_404(AgrovetSale, pk=pk)

    if not _must_own_sale_if_locked_user(request, sale):
        messages.error(request, "You do not have permission to add payment for this sale.")
        return redirect("agrovet:sale_list")

    if request.method != "POST":
        return redirect("agrovet:sale_detail", pk=sale.pk)

    form = _style_form_fields(AgrovetPaymentForm(request.POST))
    if not form.is_valid():
        messages.error(request, "Please enter valid payment details.")
        return redirect("agrovet:sale_detail", pk=sale.pk)

    payment = form.save(commit=False)
    payment.sale = sale
    payment.created_by = request.user
    payment.save()

    messages.success(request, "Payment added successfully.")
    return redirect("agrovet:sale_detail", pk=sale.pk)


# =========================================================
# EXPENSES
# =========================================================
@login_required
@role_required(["admin", "cashier", "seller", "agrovet"])
def expense_create(request):
    if request.method == "POST":
        post_data = request.POST.copy()
        if _is_seller(request) or _is_agrovet(request):
            locked_branch = _get_user_branch(request)
            if locked_branch and "branch" in post_data:
                post_data["branch"] = str(locked_branch.id)

        form = _style_form_fields(AgrovetExpenseForm(post_data))

        if form.is_valid():
            obj = form.save(commit=False)

            if _is_seller(request) or _is_agrovet(request):
                locked_branch = _get_user_branch(request)
                if locked_branch:
                    obj.branch = locked_branch

            obj.created_by = request.user
            obj.save()

            messages.success(request, "Expense added successfully.")
            return redirect("agrovet:expense_list")

        messages.error(request, "Please fix the errors below.")
    else:
        form = _style_form_fields(AgrovetExpenseForm())

        if _is_seller(request) or _is_agrovet(request):
            locked_branch = _get_user_branch(request)
            if locked_branch and "branch" in form.fields:
                form.fields["branch"].initial = locked_branch
                form.fields["branch"].widget.attrs["disabled"] = True

    return render(request, "agrovet/expense_form.html", {"form": form})


@login_required
@role_required(["admin", "cashier", "seller", "agrovet"])
def expense_list(request):
    branch = _selected_branch(request)
    qs = _expense_scope_qs(request)

    if branch and _can_choose_branch(request):
        qs = qs.filter(branch=branch)

    page_obj = Paginator(qs.order_by("-date", "-id"), 20).get_page(request.GET.get("page", 1))

    context = {
        **_branch_context(request, branch),
        "expenses": page_obj.object_list,
        "page_obj": page_obj,
    }
    return render(request, "agrovet/expense_list.html", context)


# =========================================================
# CUSTOMERS
# =========================================================
@login_required
@role_required(["admin", "cashier", "seller", "agrovet"])
def customer_list(request):
    q = (request.GET.get("q") or "").strip()
    branch = _selected_branch(request)

    qs = AgrovetCustomer.objects.all().order_by("name", "-id")

    if _is_seller(request) or _is_agrovet(request):
        customer_ids = _sale_scope_qs(request).exclude(customer__isnull=True).values_list("customer_id", flat=True)
        qs = qs.filter(id__in=customer_ids).distinct()
    elif branch and _can_choose_branch(request):
        customer_ids = AgrovetSale.objects.filter(branch=branch).exclude(customer__isnull=True).values_list("customer_id", flat=True)
        qs = qs.filter(id__in=customer_ids).distinct()

    if q:
        qs = qs.filter(
            Q(name__icontains=q) |
            Q(phone__icontains=q) |
            Q(location__icontains=q)
        )

    page_obj = Paginator(qs, 20).get_page(request.GET.get("page", 1))

    return render(request, "agrovet/customer_list.html", {
        **_branch_context(request, branch),
        "customers": page_obj.object_list,
        "page_obj": page_obj,
        "query": q,
    })