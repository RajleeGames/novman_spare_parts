from decimal import Decimal
from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models

from inventory.models import Branch


class ServiceRecord(models.Model):
    SERVICE_COMPRESSOR = "compressor_machine"
    SERVICE_WELDING = "welding_machine"

    SERVICE_CHOICES = [
        (SERVICE_COMPRESSOR, "Compressor Machine"),
        (SERVICE_WELDING, "Welding Machine"),
    ]

    branch = models.ForeignKey(
        Branch,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="service_records",
    )
    service_type = models.CharField(max_length=50, choices=SERVICE_CHOICES)
    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    customer_name = models.CharField(max_length=150, blank=True, default="")
    customer_phone = models.CharField(max_length=30, blank=True, default="")
    notes = models.TextField(blank=True, default="")

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_services",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Service Record"
        verbose_name_plural = "Service Records"

    def __str__(self):
        return f"{self.get_service_type_display()} - {self.amount}"