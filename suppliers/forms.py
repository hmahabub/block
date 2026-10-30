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

    def clean_tin(self):
        value = (self.cleaned_data.get('tin') or '').strip()
        if value:
            clash = Supplier.objects.filter(tin__iexact=value).exclude(pk=self.instance.pk).first()
            if clash:
                raise forms.ValidationError(f'TIN {value} already belongs to supplier {clash.supplier_code} ({clash.name}).')
        return value

    def clean_phone(self):
        return normalize_phone(self.cleaned_data.get('phone', ''))
