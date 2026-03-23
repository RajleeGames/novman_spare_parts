from decimal import Decimal
import uuid

from django.db import models, transaction
from django.db.models import Sum
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.db.models.signals import post_delete
from django.dispatch import receiver


# -------------------------
# Branch model
# -------------------------
class Branch(models.Model):
    name = models.CharField(max_length=120, unique=True)
    code = models.CharField(max_length=20, blank=True, null=True)
    address = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    @classmethod
    def get_default_branch(cls):
        return (
            cls.objects.filter(is_active=True).order_by("id").first()
            or cls.objects.order_by("id").first()
        )


# -------------------------
# Category / Supplier / Product
# -------------------------
class Category(models.Model):
    name = models.CharField(max_length=255, unique=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Supplier(models.Model):
    name = models.CharField(max_length=255)
    contact = models.CharField(max_length=100, blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Product(models.Model):
    name = models.CharField(max_length=255)
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True, blank=True)
    supplier = models.ForeignKey(Supplier, on_delete=models.SET_NULL, null=True, blank=True)

    # Keep these for compatibility with your existing pages/forms/reports
    # buying_price can be treated as "latest buying price"
    # selling_price can be treated as "default selling price"
    buying_price = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    selling_price = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))

    # Cached total stock across branches
    stock = models.IntegerField(
        default=0,
        help_text="(Auto) Total stock across branches — do not edit manually."
    )

    barcode = models.CharField(max_length=50, unique=True, blank=True)
    reorder_level = models.PositiveIntegerField(default=10)

    class Meta:
        ordering = ["-id"]

    def __str__(self):
        return self.name

    def profit_per_unit(self):
        return (self.selling_price or Decimal("0.00")) - (self.buying_price or Decimal("0.00"))

    def _generate_unique_barcode(self):
        for _ in range(10):
            code = str(uuid.uuid4().int)[:12]
            if not Product.objects.filter(barcode=code).exists():
                return code
        return str(uuid.uuid4().int)[:12]

    @staticmethod
    def recalc_total_stock(product_id: int) -> int:
        total = ProductStock.objects.filter(product_id=product_id).aggregate(
            total=Sum("quantity")
        )["total"] or 0
        Product.objects.filter(pk=product_id).update(stock=int(total))
        return int(total)

    def total_batch_stock(self):
        return self.batches.aggregate(total=Sum("quantity_remaining"))["total"] or 0

    def save(self, *args, **kwargs):
        if not self.barcode:
            self.barcode = self._generate_unique_barcode()
        super().save(*args, **kwargs)


# -------------------------
# Per-branch stock
# -------------------------
class ProductStock(models.Model):
    """
    Holds quantity of a product per branch.
    Unique per (product, branch).
    """
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="branch_stocks")
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name="product_stocks")
    quantity = models.IntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["product", "branch"], name="uniq_product_branch_stock")
        ]
        ordering = ["product_id", "branch_id"]

    def __str__(self):
        return f"{self.product.name} @ {self.branch.name}: {self.quantity}"

    def clean(self):
        if self.quantity < 0:
            raise ValidationError("Branch stock quantity cannot be negative.")

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)
        Product.recalc_total_stock(self.product_id)


# -------------------------
# Product Batch (NEW)
# -------------------------
class ProductBatch(models.Model):
    """
    Each purchase/add-stock operation creates a separate batch.

    Example:
    - Batch 1: buy @ 3000, qty 10
    - Batch 2: buy @ 2000, qty 15

    FIFO selling will consume oldest remaining batch first.
    """
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="batches")
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name="batches")

    buying_price = models.DecimalField(max_digits=12, decimal_places=2)
    selling_price = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))

    quantity_added = models.PositiveIntegerField()
    quantity_remaining = models.PositiveIntegerField()

    supplier = models.ForeignKey(Supplier, on_delete=models.SET_NULL, null=True, blank=True)
    note = models.CharField(max_length=255, blank=True)

    # link back to stock entry that created this batch
    stock_entry = models.OneToOneField(
        "StockEntry",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_batch",
    )

    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["created_at", "id"]
        indexes = [
            models.Index(fields=["product", "branch", "created_at"]),
        ]

    def __str__(self):
        return (
            f"{self.product.name} | {self.branch.name} | "
            f"Buy {self.buying_price} | Rem {self.quantity_remaining}/{self.quantity_added}"
        )

    def clean(self):
        if self.quantity_added < 0:
            raise ValidationError("quantity_added cannot be negative.")
        if self.quantity_remaining < 0:
            raise ValidationError("quantity_remaining cannot be negative.")
        if self.quantity_remaining > self.quantity_added:
            raise ValidationError("quantity_remaining cannot exceed quantity_added.")

    @property
    def sold_quantity(self):
        return self.quantity_added - self.quantity_remaining

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)


# -------------------------
# StockEntry (history + ONLY place that changes stock)
# -------------------------
class StockEntry(models.Model):
    """
    Records every change in stock.

    RULES:
    - Creating a StockEntry adjusts ProductStock.quantity ONLY HERE.
    - Positive change => adds stock and creates a ProductBatch.
    - Negative change => removes stock using FIFO from ProductBatch.
    - Editing existing entry's product/branch/change is FORBIDDEN.
    - Deleting a StockEntry reverses its effect safely.
    """

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="stock_entries")
    change = models.IntegerField(help_text="Positive if stock was added, negative if removed")
    branch = models.ForeignKey(
        Branch,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="stock_entries"
    )
    timestamp = models.DateTimeField(default=timezone.now)
    note = models.CharField(max_length=255, blank=True)

    # batch pricing info
    unit_cost = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Buying price per unit for positive stock entries."
    )
    unit_selling_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Selling price per unit for the created batch (optional, defaults to product.selling_price)."
    )

    class Meta:
        ordering = ["-timestamp", "-id"]

    def __str__(self):
        sign = "+" if self.change >= 0 else ""
        branch_name = self.branch.name if self.branch else "Auto"
        return f"{self.product.name} ({branch_name}): {sign}{self.change} @ {self.timestamp:%Y-%m-%d %H:%M}"

    def _effective_branch(self):
        if self.branch_id:
            return self.branch
        return Branch.get_default_branch()

    def _apply_positive_batch(self):
        if self.change <= 0:
            return

        buying_price = self.unit_cost
        if buying_price is None:
            buying_price = self.product.buying_price or Decimal("0.00")

        selling_price = self.unit_selling_price
        if selling_price is None:
            selling_price = self.product.selling_price or Decimal("0.00")

        ProductBatch.objects.create(
            product=self.product,
            branch=self.branch,
            buying_price=buying_price,
            selling_price=selling_price,
            quantity_added=self.change,
            quantity_remaining=self.change,
            supplier=self.product.supplier,
            note=self.note or "",
            stock_entry=self,
            created_at=self.timestamp,
        )

        # keep latest/default product prices updated
        Product.objects.filter(pk=self.product_id).update(
            buying_price=buying_price,
            selling_price=selling_price,
        )

    def _consume_fifo_batches(self):
        if self.change >= 0:
            return

        needed = abs(int(self.change))

        batches = ProductBatch.objects.select_for_update().filter(
            product_id=self.product_id,
            branch_id=self.branch_id,
            quantity_remaining__gt=0
        ).order_by("created_at", "id")

        total_available = sum(b.quantity_remaining for b in batches)
        if total_available < needed:
            raise ValidationError(
                f"Not enough FIFO batch stock for '{self.product.name}' in branch '{self.branch.name}'. "
                f"Needed: {needed}, available in batches: {total_available}."
            )

        for batch in batches:
            if needed <= 0:
                break

            take = min(batch.quantity_remaining, needed)
            if take <= 0:
                continue

            batch.quantity_remaining -= take
            batch.save(update_fields=["quantity_remaining"])

            StockConsumption.objects.create(
                stock_entry=self,
                batch=batch,
                quantity=take,
                unit_cost=batch.buying_price,
                unit_selling_price=batch.selling_price,
            )

            needed -= take

    def save(self, *args, **kwargs):
        is_new = self._state.adding

        if not is_new:
            old = StockEntry.objects.get(pk=self.pk)
            if (
                old.change != self.change
                or old.product_id != self.product_id
                or old.branch_id != self.branch_id
            ):
                raise ValidationError(
                    "You cannot edit product/branch/change of an existing StockEntry. "
                    "Create a new StockEntry adjustment instead."
                )
            return super().save(*args, **kwargs)

        self.branch = self._effective_branch()
        if not self.branch:
            raise ValidationError("No branch found. Create at least one Branch before adding stock.")

        if self.change == 0:
            raise ValidationError("Stock change cannot be zero.")

        with transaction.atomic():
            super().save(*args, **kwargs)

            ps, _ = ProductStock.objects.select_for_update().get_or_create(
                product_id=self.product_id,
                branch_id=self.branch_id,
                defaults={"quantity": 0},
            )

            new_qty = int(ps.quantity) + int(self.change)
            if new_qty < 0:
                raise ValidationError(
                    f"Insufficient stock in branch '{self.branch.name}' for '{self.product.name}'. "
                    f"Available: {ps.quantity}, change: {self.change}"
                )

            ps.quantity = new_qty
            ps.save(update_fields=["quantity"])

            if self.change > 0:
                self._apply_positive_batch()

            if self.change < 0:
                self._consume_fifo_batches()

    def delete(self, *args, **kwargs):
        branch = self._effective_branch()
        if not branch:
            raise ValidationError("Cannot delete StockEntry because no branch exists.")

        with transaction.atomic():
            ps = ProductStock.objects.select_for_update().filter(
                product=self.product,
                branch=branch
            ).first()

            if not ps:
                raise ValidationError("Cannot delete: branch stock row is missing.")

            new_qty = int(ps.quantity) - int(self.change)
            if new_qty < 0:
                raise ValidationError("Cannot delete this StockEntry because it would make stock negative.")

            if self.change > 0:
                batch = getattr(self, "created_batch", None)
                if batch:
                    if batch.quantity_remaining != batch.quantity_added:
                        raise ValidationError(
                            "Cannot delete this stock-add entry because some quantity from its batch "
                            "has already been sold/consumed."
                        )
                    batch.delete()

            if self.change < 0:
                consumptions = self.batch_consumptions.select_related("batch").select_for_update().order_by("-id")
                for c in consumptions:
                    batch = c.batch
                    batch.quantity_remaining += c.quantity
                    if batch.quantity_remaining > batch.quantity_added:
                        raise ValidationError(
                            f"Cannot reverse consumption for batch #{batch.id}; quantity would exceed original batch."
                        )
                    batch.save(update_fields=["quantity_remaining"])
                consumptions.delete()

            ps.quantity = new_qty
            ps.save(update_fields=["quantity"])

            return super().delete(*args, **kwargs)


# -------------------------
# Stock consumption (NEW)
# -------------------------
class StockConsumption(models.Model):
    """
    Tracks how a negative StockEntry consumed one or more FIFO batches.

    Example:
    - sold 7 units
    - 5 taken from batch 1
    - 2 taken from batch 2
    => two StockConsumption rows
    """
    stock_entry = models.ForeignKey(
        StockEntry,
        on_delete=models.CASCADE,
        related_name="batch_consumptions"
    )
    batch = models.ForeignKey(
        ProductBatch,
        on_delete=models.PROTECT,
        related_name="consumptions"
    )
    quantity = models.PositiveIntegerField()

    # snapshot prices at the time of consumption
    unit_cost = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    unit_selling_price = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.stock_entry.product.name} <- batch {self.batch_id} x {self.quantity}"

    @property
    def profit(self):
        return (self.unit_selling_price - self.unit_cost) * self.quantity

    def clean(self):
        if self.quantity <= 0:
            raise ValidationError("Consumption quantity must be greater than zero.")

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)


# -------------------------
# Signal: recalc cached total when ProductStock is deleted
# -------------------------
@receiver(post_delete, sender=ProductStock)
def recalc_product_stock_after_delete(sender, instance, **kwargs):
    Product.recalc_total_stock(instance.product_id)