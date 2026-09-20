from django import forms
from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils import timezone

from .models import SupplierPayment


class SupplierPaymentForm(forms.ModelForm):
    class Meta:
        model = SupplierPayment
        fields = ['project_cost', 'supplier', 'payment_date', 'amount', 'payment_method', 'reference_no', 'notes']
        widgets = {
            'payment_date': forms.DateInput(attrs={'type': 'date'}),
            'notes': forms.Textarea(attrs={'rows': 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.instance.pk:
            self.fields['payment_date'].initial = timezone.now().date()

    def clean(self):
        cleaned_data = super().clean()
        project_cost = cleaned_data.get('project_cost')
        amount = cleaned_data.get('amount')
        if project_cost and amount is not None:
            remaining = project_cost.payable_amount
            if amount > remaining:
                symbol = settings.CURRENCY_SYMBOL
                raise ValidationError(
                    f"This payment of {symbol}{amount} exceeds the remaining payable amount of "
                    f"{symbol}{remaining} for this cost entry."
                )
        return cleaned_data
