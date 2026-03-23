from django.contrib import admin
from .models import (
    AgrovetSale,
    AgrovetExpense,
    AgrovetPayment,
    AgrovetCustomer,
    AgrovetProduct,
)


@admin.register(AgrovetCustomer)
class AgrovetCustomerAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "phone", "location", "created_at")
    search_fields = ("name", "phone", "location")
    list_per_page = 25


@admin.register(AgrovetProduct)
class AgrovetProductAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
        "category",
        "branch",
        "unit",
        "buying_price",
        "selling_price",
        "stock_qty",
        "reorder_level",
        "is_active",
        "created_at",
    )
    search_fields = (
        "name",
        "category",
        "unit",
        "branch__name",
        "note",
    )
    list_filter = (
        "branch",
        "category",
        "unit",
        "is_active",
        "created_at",
    )
    list_editable = (
        "buying_price",
        "selling_price",
        "stock_qty",
        "reorder_level",
        "is_active",
    )
    ordering = ("name", "-id")
    list_per_page = 30


@admin.register(AgrovetSale)
class AgrovetSaleAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "item_name",
        "product",
        "customer",
        "branch",
        "payment_method",
        "quantity",
        "selling_price",
        "amount_paid",
        "sold_at",
    )
    search_fields = (
        "item_name",
        "category",
        "customer__name",
        "customer__phone",
        "product__name",
    )
    list_filter = (
        "payment_method",
        "branch",
        "category",
        "sold_at",
    )
    list_per_page = 25


@admin.register(AgrovetExpense)
class AgrovetExpenseAdmin(admin.ModelAdmin):
    list_display = ("id", "date", "category", "branch", "amount", "created_by")
    search_fields = ("category", "description", "branch__name")
    list_filter = ("date", "branch", "category")
    list_per_page = 25


@admin.register(AgrovetPayment)
class AgrovetPaymentAdmin(admin.ModelAdmin):
    list_display = ("id", "sale", "amount", "paid_at", "created_by")
    search_fields = ("sale__item_name", "sale__customer__name", "note")
    list_filter = ("paid_at",)
    list_per_page = 25