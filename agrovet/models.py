from decimal import Decimal
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import Sum
from django.utils import timezone
from inventory.models import Branch


def dec(value, default="0.00"):
    try:
        return Decimal(str(value if value is not None else default))
    except Exception:
        return Decimal(default)


class AgrovetCustomer(models.Model):
    name = models.CharField(max_length=150, default="Customer")
    phone = models.CharField(max_length=50, blank=True, default="")
    location = models.CharField(max_length=150, blank=True, default="")
    note = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name", "-id"]

    def __str__(self):
        return self.name or f"Customer #{self.pk}"


class AgrovetProduct(models.Model):
    branch = models.ForeignKey(
        Branch,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="agrovet_products",
    )
    name = models.CharField(max_length=200)
    category = models.CharField(max_length=120, blank=True, default="")
    unit = models.CharField(max_length=30, blank=True, default="pcs")

    buying_price = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    selling_price = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    stock_qty = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    reorder_level = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    is_active = models.BooleanField(default=True)
    note = models.TextField(blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name", "-id"]
        indexes = [
            models.Index(fields=["name"]),
            models.Index(fields=["branch", "name"]),
            models.Index(fields=["category"]),
            models.Index(fields=["is_active"]),
        ]
        unique_together = ("branch", "name")

    def __str__(self):
        branch_name = self.branch.name if self.branch else "No Branch"
        return f"{self.name} ({branch_name})"

    @property
    def stock_status(self):
        qty = dec(self.stock_qty)
        reorder = dec(self.reorder_level)
        if qty <= 0:
            return "out"
        if reorder > 0 and qty <= reorder:
            return "low"
        return "ok"


class AgrovetSale(models.Model):
    PAYMENT_CASH = "cash"
    PAYMENT_BANK = "bank"
    PAYMENT_MOBILE = "mobile"
    PAYMENT_DEBT = "debt"

    PAYMENT_CHOICES = [
        (PAYMENT_CASH, "Cash"),
        (PAYMENT_BANK, "Bank"),
        (PAYMENT_MOBILE, "Mobile"),
        (PAYMENT_DEBT, "Debt"),
    ]

    branch = models.ForeignKey(
        Branch,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="agrovet_sales",
    )

    customer = models.ForeignKey(
        AgrovetCustomer,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sales",
    )

    product = models.ForeignKey(
        AgrovetProduct,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sales",
    )

    item_name = models.CharField(max_length=200)
    category = models.CharField(max_length=120, blank=True, default="")
    quantity = models.DecimalField(max_digits=12, decimal_places=2, default=1)
    unit = models.CharField(max_length=30, blank=True, default="pcs")

    buying_price = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    selling_price = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    payment_method = models.CharField(
        max_length=20,
        choices=PAYMENT_CHOICES,
        default=PAYMENT_CASH,
    )
    amount_paid = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    note = models.TextField(blank=True, default="")

    sold_at = models.DateTimeField(default=timezone.now)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="agrovet_sales_created",
    )

    class Meta:
        ordering = ["-sold_at", "-id"]
        indexes = [
            models.Index(fields=["sold_at"]),
            models.Index(fields=["branch", "sold_at"]),
            models.Index(fields=["payment_method"]),
            models.Index(fields=["item_name"]),
        ]

    def __str__(self):
        return f"{self.item_name} - {self.quantity}"

    def clean(self):
        qty = dec(self.quantity)
        buy = dec(self.buying_price)
        sell = dec(self.selling_price)
        paid = dec(self.amount_paid)

        if qty <= 0:
            raise ValidationError("Quantity must be greater than 0.")
        if buy < 0:
            raise ValidationError("Buying price cannot be negative.")
        if sell < 0:
            raise ValidationError("Selling price cannot be negative.")
        if paid < 0:
            raise ValidationError("Amount paid cannot be negative.")
        if paid > self.total_selling:
            raise ValidationError("Amount paid cannot be greater than total selling amount.")

        # check stock before save for new sale
        if self.product_id and not self.pk:
            product = AgrovetProduct.objects.filter(pk=self.product_id).first()
            if product:
                available = dec(product.stock_qty)
                if qty > available:
                    raise ValidationError(
                        f"Not enough stock for {product.name}. Available: {available}, requested: {qty}."
                    )

    def save(self, *args, **kwargs):
        is_new = self.pk is None

        with transaction.atomic():
            locked_product = None

            if self.product_id:
                locked_product = AgrovetProduct.objects.select_for_update().filter(pk=self.product_id).first()

            # copy snapshot values from product
            if locked_product:
                if not self.branch and locked_product.branch:
                    self.branch = locked_product.branch

                if not (self.item_name or "").strip():
                    self.item_name = locked_product.name

                if not (self.category or "").strip():
                    self.category = locked_product.category or ""

                if not (self.unit or "").strip():
                    self.unit = locked_product.unit or "pcs"

                if dec(self.buying_price) <= 0:
                    self.buying_price = locked_product.buying_price or 0

                if dec(self.selling_price) <= 0:
                    self.selling_price = locked_product.selling_price or 0

            self.full_clean()
            super().save(*args, **kwargs)

            # subtract stock only once when creating new sale
            if is_new and locked_product:
                qty = dec(self.quantity)

                if qty > dec(locked_product.stock_qty):
                    raise ValidationError(
                        f"Not enough stock for {locked_product.name}. Available: {locked_product.stock_qty}, requested: {qty}."
                    )

                locked_product.stock_qty = dec(locked_product.stock_qty) - qty
                locked_product.save(update_fields=["stock_qty", "updated_at"])

    @property
    def total_buying(self):
        return dec(self.buying_price) * dec(self.quantity)

    @property
    def total_selling(self):
        return dec(self.selling_price) * dec(self.quantity)

    @property
    def profit(self):
        return self.total_selling - self.total_buying

    @property
    def payments_total(self):
        return dec(self.payments.aggregate(t=Sum("amount"))["t"] or 0)

    @property
    def total_paid(self):
        return dec(self.amount_paid) + self.payments_total

    @property
    def balance(self):
        bal = self.total_selling - self.total_paid
        return bal if bal > 0 else Decimal("0.00")

    @property
    def is_debt(self):
        return self.payment_method == self.PAYMENT_DEBT

    @property
    def is_fully_paid(self):
        return self.balance <= 0


class AgrovetExpense(models.Model):
    branch = models.ForeignKey(
        Branch,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="agrovet_expenses",
    )
    date = models.DateField(default=timezone.localdate)
    category = models.CharField(max_length=100, default="General")
    description = models.CharField(max_length=255, blank=True, default="")
    amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="agrovet_expenses_created",
    )

    class Meta:
        ordering = ["-date", "-id"]
        indexes = [
            models.Index(fields=["date"]),
            models.Index(fields=["branch", "date"]),
            models.Index(fields=["category"]),
        ]

    def __str__(self):
        return f"{self.category} - {self.amount}"

    def clean(self):
        if dec(self.amount) < 0:
            raise ValidationError("Expense amount cannot be negative.")


class AgrovetPayment(models.Model):
    sale = models.ForeignKey(
        AgrovetSale,
        on_delete=models.CASCADE,
        related_name="payments",
    )
    amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    paid_at = models.DateTimeField(default=timezone.now)
    note = models.CharField(max_length=255, blank=True, default="")

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="agrovet_payments_created",
    )

    class Meta:
        ordering = ["-paid_at", "-id"]
        indexes = [
            models.Index(fields=["paid_at"]),
            models.Index(fields=["sale", "paid_at"]),
        ]

    def __str__(self):
        return f"Payment {self.amount} for sale #{self.sale_id}"

    def clean(self):
        amount = dec(self.amount)
        if amount <= 0:
            raise ValidationError("Payment amount must be greater than 0.")

        if self.sale_id:
            remaining = self.sale.balance
            if self.pk:
                old = AgrovetPayment.objects.filter(pk=self.pk).first()
                if old:
                    remaining = remaining + dec(old.amount)

            if amount > remaining:
                raise ValidationError(f"Payment cannot exceed sale balance ({remaining}).")

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)