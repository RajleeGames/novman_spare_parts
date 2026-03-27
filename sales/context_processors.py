from django.db.models import Sum
from django.utils import timezone

from .models import Expense, Invoice


def debt_invoices_sidebar(request):
    try:
        if not request.user.is_authenticated:
            return {"debt_invoices_sidebar": Invoice.objects.none()}

        user = request.user
        profile = getattr(user, "profile", None)
        role = getattr(profile, "role", None)
        branch = getattr(profile, "branch", None)

        qs = Invoice.objects.filter(status="debt", paid=False)

        if role == "seller" and branch and hasattr(Invoice, "branch"):
            qs = qs.filter(branch=branch)

        return {
            "debt_invoices_sidebar": qs.order_by("-id")
        }
    except Exception:
        return {"debt_invoices_sidebar": Invoice.objects.none()}


def today_expenses(request):
    try:
        if not request.user.is_authenticated:
            return {
                "today_expense_total": 0,
                "today_expenses_list": Expense.objects.none(),
            }

        user = request.user
        profile = getattr(user, "profile", None)
        role = getattr(profile, "role", None)
        branch = getattr(profile, "branch", None)

        today = timezone.localdate()
        todays_qs = Expense.objects.filter(date=today)

        if role == "seller" and branch and hasattr(Expense, "branch"):
            todays_qs = todays_qs.filter(branch=branch)

        todays_qs = todays_qs.order_by("-id")
        total = todays_qs.aggregate(sum=Sum("amount"))["sum"] or 0

        return {
            "today_expense_total": total,
            "today_expenses_list": todays_qs,
        }
    except Exception:
        return {
            "today_expense_total": 0,
            "today_expenses_list": Expense.objects.none(),
        }