# nova_spareparts/urls.py
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

from users.views import RoleBasedLoginView
from django.contrib.auth.views import LogoutView
from sales.views import dashboard_redirect


# Allow GET on logout
class LogoutViaGet(LogoutView):
    http_method_names = ["get", "post"]


urlpatterns = [
    # Landing always redirects by role
    path("", dashboard_redirect, name="dashboard"),

    # Django admin
    path("admin/", admin.site.urls),

    # Auth
    path("login/", RoleBasedLoginView.as_view(), name="login"),
    path("logout/", LogoutViaGet.as_view(next_page="login"), name="logout"),

    # Sales app
    path("seller/", include(("sales.urls", "sales"), namespace="sales")),

    # Contacts
    path("contacts/", include("contacts.urls")),

    # Users app
    path("users/", include(("users.urls", "users"), namespace="users")),

    # Agrovet app
    path("agrovet/", include(("agrovet.urls", "agrovet"), namespace="agrovet")),

    
]

# Branding
admin.site.site_header = "NOVA AUTO SPARE PARTS ADMIN"
admin.site.site_title = "NOVA AUTO SPARE PARTS ADMIN PORTAL"
admin.site.index_title = "Welcome to NOVA AUTO SPARE PARTS MANAGEMENT"

# Static + Media (DEV only)
if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.BASE_DIR / "static")
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)