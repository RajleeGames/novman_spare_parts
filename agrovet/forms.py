from decimal import Decimal
from django import forms
from .models import (
    AgrovetSale,
    AgrovetExpense,
    AgrovetPayment,
    AgrovetCustomer,
    AgrovetProduct,
)


class DateInput(forms.DateInput):
    input_type = "date"


class DateTimeInput(forms.DateTimeInput):
    input_type = "datetime-local"


class AgrovetSaleForm(forms.ModelForm):
    customer_name = forms.CharField(
        required=False,
        label="Customer Name",
        widget=forms.TextInput(attrs={
            "placeholder": "Enter customer name",
        }),
    )

    customer_phone = forms.CharField(
        required=False,
        label="Customer Phone",
        widget=forms.TextInput(attrs={
            "placeholder": "Enter phone number",
        }),
    )

    class Meta:
        model = AgrovetSale
        fields = [
            "branch",
            "product",
            "item_name",
            "category",
            "quantity",
            "unit",
            "buying_price",
            "selling_price",
            "payment_method",
            "amount_paid",
            "note",
        ]
        widgets = {
            "branch": forms.Select(),
            "product": forms.Select(),
            "item_name": forms.HiddenInput(),
            "category": forms.HiddenInput(),
            "unit": forms.HiddenInput(),
            "buying_price": forms.HiddenInput(),
            "selling_price": forms.HiddenInput(),
            "quantity": forms.NumberInput(attrs={
                "placeholder": "Enter quantity",
                "step": "0.01",
                "min": "0.01",
            }),
            "payment_method": forms.Select(),
            "amount_paid": forms.NumberInput(attrs={
                "placeholder": "Amount paid now",
                "step": "0.01",
                "min": "0",
            }),
            "note": forms.Textarea(attrs={
                "placeholder": "Extra note about this sale",
                "rows": 3,
            }),
        }
        labels = {
            "branch": "Branch",
            "product": "Product",
            "quantity": "Quantity",
            "payment_method": "Payment Method",
            "amount_paid": "Amount Paid",
            "note": "Note",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["product"].queryset = AgrovetProduct.objects.filter(is_active=True).order_by("name")
        self.fields["product"].required = False
        self.fields["product"].empty_label = "Select saved product"

        self.fields["payment_method"].choices = [
            ("cash", "Cash"),
            ("bank", "Bank"),
            ("mobile", "Mobile"),
        ]

        for name, field in self.fields.items():
            if isinstance(field.widget, forms.HiddenInput):
                continue
            elif isinstance(field.widget, forms.Select):
                field.widget.attrs["class"] = "form-select"
            elif isinstance(field.widget, forms.Textarea):
                field.widget.attrs["class"] = "form-control"
            else:
                field.widget.attrs["class"] = "form-control"

    def clean(self):
        cleaned = super().clean()

        product = cleaned.get("product")
        item_name = (cleaned.get("item_name") or "").strip()
        category = (cleaned.get("category") or "").strip()
        unit = (cleaned.get("unit") or "").strip()

        quantity = cleaned.get("quantity") or Decimal("0")
        buying_price = cleaned.get("buying_price") or Decimal("0")
        selling_price = cleaned.get("selling_price") or Decimal("0")
        amount_paid = cleaned.get("amount_paid") or Decimal("0")
        payment_method = cleaned.get("payment_method")

        if product:
            if not cleaned.get("branch") and product.branch:
                cleaned["branch"] = product.branch

            cleaned["item_name"] = product.name or item_name
            cleaned["category"] = product.category or category
            cleaned["unit"] = product.unit or unit or "pcs"
            cleaned["buying_price"] = product.buying_price or buying_price or Decimal("0")
            cleaned["selling_price"] = product.selling_price or selling_price or Decimal("0")

            item_name = cleaned["item_name"]
            category = cleaned["category"]
            unit = cleaned["unit"]
            buying_price = cleaned["buying_price"]
            selling_price = cleaned["selling_price"]

        if not item_name:
            self.add_error("product", "Please select a product.")

        if quantity <= 0:
            self.add_error("quantity", "Quantity must be greater than zero.")

        if buying_price < 0:
            self.add_error("product", "Buying price cannot be negative.")

        if selling_price < 0:
            self.add_error("product", "Selling price cannot be negative.")

        if amount_paid < 0:
            self.add_error("amount_paid", "Amount paid cannot be negative.")

        total = Decimal(selling_price or 0) * Decimal(quantity or 0)

        if amount_paid > total and total > 0:
            self.add_error("amount_paid", "Amount paid cannot be greater than total sale amount.")

        if payment_method in ["cash", "bank", "mobile"] and total > 0 and amount_paid <= 0:
            cleaned["amount_paid"] = total

        return cleaned


class AgrovetExpenseForm(forms.ModelForm):
    class Meta:
        model = AgrovetExpense
        fields = ["branch", "date", "category", "description", "amount"]
        widgets = {
            "branch": forms.Select(),
            "date": DateInput(),
            "category": forms.TextInput(attrs={
                "placeholder": "e.g. Rent, Labour, Electricity, Feed Transport",
            }),
            "description": forms.TextInput(attrs={
                "placeholder": "Short expense description",
            }),
            "amount": forms.NumberInput(attrs={
                "placeholder": "Expense amount",
                "step": "0.01",
                "min": "0",
            }),
        }
        labels = {
            "branch": "Branch",
            "date": "Date",
            "category": "Category",
            "description": "Description",
            "amount": "Amount",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        for _, field in self.fields.items():
            if isinstance(field.widget, forms.Select):
                field.widget.attrs["class"] = "form-select"
            else:
                field.widget.attrs["class"] = "form-control"

    def clean_amount(self):
        amount = self.cleaned_data.get("amount")
        if amount is not None and amount < 0:
            raise forms.ValidationError("Amount cannot be negative.")
        return amount


class AgrovetPaymentForm(forms.ModelForm):
    class Meta:
        model = AgrovetPayment
        fields = ["amount", "paid_at", "note"]
        widgets = {
            "amount": forms.NumberInput(attrs={
                "placeholder": "Payment amount",
                "step": "0.01",
                "min": "0",
            }),
            "paid_at": DateTimeInput(),
            "note": forms.TextInput(attrs={
                "placeholder": "Payment note",
            }),
        }
        labels = {
            "amount": "Amount",
            "paid_at": "Payment Date & Time",
            "note": "Note",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        for _, field in self.fields.items():
            field.widget.attrs["class"] = "form-control"

    def clean_amount(self):
        amount = self.cleaned_data.get("amount")
        if amount is not None and amount <= 0:
            raise forms.ValidationError("Payment amount must be greater than zero.")
        return amount


class AgrovetCustomerForm(forms.ModelForm):
    class Meta:
        model = AgrovetCustomer
        fields = ["name", "phone", "location", "note"]
        widgets = {
            "name": forms.TextInput(attrs={
                "placeholder": "Customer full name",
            }),
            "phone": forms.TextInput(attrs={
                "placeholder": "Phone number",
            }),
            "location": forms.TextInput(attrs={
                "placeholder": "Customer location",
            }),
            "note": forms.Textarea(attrs={
                "placeholder": "Extra note about customer",
                "rows": 3,
            }),
        }
        labels = {
            "name": "Name",
            "phone": "Phone",
            "location": "Location",
            "note": "Note",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        for _, field in self.fields.items():
            field.widget.attrs["class"] = "form-control"

    def clean_name(self):
        name = (self.cleaned_data.get("name") or "").strip()
        return name or "Customer"


class AgrovetProductForm(forms.ModelForm):
    class Meta:
        model = AgrovetProduct
        fields = [
            "branch",
            "name",
            "category",
            "unit",
            "buying_price",
            "selling_price",
            "stock_qty",
            "reorder_level",
            "is_active",
            "note",
        ]
        widgets = {
            "branch": forms.Select(),
            "name": forms.TextInput(attrs={
                "placeholder": "Product name",
            }),
            "category": forms.TextInput(attrs={
                "placeholder": "e.g. Feed, Vaccine, Medicine, Supplement",
            }),
            "unit": forms.TextInput(attrs={
                "placeholder": "e.g. bag, pcs, bottle, kg",
            }),
            "buying_price": forms.NumberInput(attrs={
                "placeholder": "Buying price",
                "step": "0.01",
                "min": "0",
            }),
            "selling_price": forms.NumberInput(attrs={
                "placeholder": "Selling price",
                "step": "0.01",
                "min": "0",
            }),
            "stock_qty": forms.NumberInput(attrs={
                "placeholder": "Current stock",
                "step": "0.01",
                "min": "0",
            }),
            "reorder_level": forms.NumberInput(attrs={
                "placeholder": "Low stock level",
                "step": "0.01",
                "min": "0",
            }),
            "is_active": forms.CheckboxInput(),
            "note": forms.Textarea(attrs={
                "placeholder": "Extra note about product",
                "rows": 3,
            }),
        }
        labels = {
            "branch": "Branch",
            "name": "Product Name",
            "category": "Category",
            "unit": "Unit",
            "buying_price": "Buying Price",
            "selling_price": "Selling Price",
            "stock_qty": "Stock Quantity",
            "reorder_level": "Reorder Level",
            "is_active": "Active",
            "note": "Note",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        for _, field in self.fields.items():
            if isinstance(field.widget, forms.Select):
                field.widget.attrs["class"] = "form-select"
            elif isinstance(field.widget, forms.Textarea):
                field.widget.attrs["class"] = "form-control"
            elif isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs["class"] = "form-check-input"
            else:
                field.widget.attrs["class"] = "form-control"

    def clean_buying_price(self):
        value = self.cleaned_data.get("buying_price")
        if value is not None and value < 0:
            raise forms.ValidationError("Buying price cannot be negative.")
        return value

    def clean_selling_price(self):
        value = self.cleaned_data.get("selling_price")
        if value is not None and value < 0:
            raise forms.ValidationError("Selling price cannot be negative.")
        return value

    def clean_stock_qty(self):
        value = self.cleaned_data.get("stock_qty")
        if value is not None and value < 0:
            raise forms.ValidationError("Stock cannot be negative.")
        return value

    def clean_reorder_level(self):
        value = self.cleaned_data.get("reorder_level")
        if value is not None and value < 0:
            raise forms.ValidationError("Reorder level cannot be negative.")
        return value