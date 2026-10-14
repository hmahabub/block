from django import forms

from core.phone import normalize_phone

from .models import Supplier


class SupplierForm(forms.ModelForm):
    class Meta:
        model = Supplier
        fields = ['name', 'owner_name', 'phone', 'email', 'tin', 'address', 'bank_account', 'cost_category', 'notes']
        widgets = {
            'address': forms.Textarea(attrs={'rows': 2}),
            'notes': forms.Textarea(attrs={'rows': 2}),
        }

    def clean_phone(self):
        return normalize_phone(self.cleaned_data.get('phone', ''))
