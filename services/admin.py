from django.contrib import admin
from .models import ServiceRecord


@admin.register(ServiceRecord)
class ServiceRecordAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "service_type",
        "amount",
        "branch",
        "customer_name",
        "customer_phone",
        "created_by",
        "created_at",
    )
    list_filter = ("service_type", "branch", "created_at")
    search_fields = ("customer_name", "customer_phone", "notes")
    ordering = ("-created_at",)