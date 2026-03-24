from django import forms
from .models import ServiceRecord


class ServiceRecordForm(forms.ModelForm):
    class Meta:
        model = ServiceRecord
        fields = [
            "branch",
            "service_type",
            "amount",
            "customer_name",
            "customer_phone",
            "notes",
        ]
        widgets = {
            "branch": forms.Select(attrs={"class": "form-select select2"}),
            "service_type": forms.Select(attrs={"class": "form-select"}),
            "amount": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "customer_name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Optional"}),
            "customer_phone": forms.TextInput(attrs={"class": "form-control", "placeholder": "Optional"}),
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 3, "placeholder": "Optional"}),
        }