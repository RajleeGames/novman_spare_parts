from django.urls import path
from . import views

app_name = "services"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("add/", views.service_create, name="service_create"),
    path("list/", views.service_list, name="service_list"),
    path("reports/", views.reports, name="reports"),
]