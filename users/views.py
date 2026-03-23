# users/views.py
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.shortcuts import redirect, render
from django.urls import reverse

from inventory.models import Branch
from .models import Profile, Role


class RoleBasedLoginView(LoginView):
    template_name = "login.html"

    def form_invalid(self, form):
        messages.error(self.request, "Login failed. Check username/password.")
        return self.render_to_response(self.get_context_data(form=form))

    def get_success_url(self):
        user = self.request.user

        # ensure profile exists
        profile, _ = Profile.objects.get_or_create(user=user)

        # direct redirect by role
        if user.is_superuser or profile.role == Role.ADMIN:
            return reverse("sales:admin_dashboard")

        if profile.role == Role.CASHIER:
            return reverse("sales:admin_dashboard")

        if profile.role == Role.SELLER:
            return reverse("sales:seller_dashboard")

        # ✅ AGROVET ROLE
        if hasattr(Role, "AGROVET") and profile.role == Role.AGROVET:
            return reverse("agrovet:dashboard")

        return reverse("dashboard")


@login_required
def profile_update(request):
    profile, _ = Profile.objects.get_or_create(user=request.user)

    is_admin = request.user.is_superuser or (profile.role == Role.ADMIN)

    if request.method == "POST":
        profile.full_name = (request.POST.get("full_name") or "").strip()
        profile.phone_number = (request.POST.get("phone_number") or "").strip()

        if request.FILES.get("picture"):
            profile.picture = request.FILES["picture"]

        # admin can change branch
        if is_admin:
            branch_id = (request.POST.get("branch") or "").strip()
            if branch_id:
                profile.branch = Branch.objects.filter(
                    pk=branch_id,
                    is_active=True
                ).first()
            else:
                profile.branch = None

        profile.save()
        messages.success(request, "Profile updated successfully.")
        return redirect("users:profile_update")

    branches = Branch.objects.filter(is_active=True).order_by("name") if is_admin else []

    return render(request, "users/profile_update.html", {
        "profile": profile,
        "branches": branches,
        "is_admin": is_admin,
    })