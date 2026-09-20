from django import forms
from django.core.exceptions import ValidationError

from .models import CustomerPayment, FlatSale


class FlatSaleForm(forms.ModelForm):
    class Meta:
        model = FlatSale
        fields = [
            'flat', 'customer', 'sale_date', 'base_price',
            'other_charges', 'discount', 'status', 'notes',
        ]
        widgets = {
            'sale_date': forms.DateInput(attrs={'type': 'date'}),
            'notes': forms.Textarea(attrs={'rows': 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Only offer flats that aren't already booked/sold elsewhere. On update,
        # also keep this sale's own flat selectable even though its status is
        # now BOOKED/SOLD because of this very sale.
        queryset = self.fields['flat'].queryset.filter(status='AVAILABLE')
        if self.instance.pk and self.instance.flat_id:
            queryset = queryset | self.fields['flat'].queryset.filter(pk=self.instance.flat_id)
        self.fields['flat'].queryset = queryset.distinct()

    def clean(self):
        cleaned_data = super().clean()
        flat = cleaned_data.get('flat')
        status = cleaned_data.get('status')
        if flat and status in (FlatSale.Status.BOOKED, FlatSale.Status.SOLD):
            conflicting = flat.sales.exclude(status=FlatSale.Status.CANCELLED)
            if self.instance.pk:
                conflicting = conflicting.exclude(pk=self.instance.pk)
            other_sale = conflicting.first()
            if other_sale:
                raise ValidationError(
                    f'{flat} already has an active sale ({other_sale.sale_no}). '
                    'Cancel that sale first before selling this flat again.'
                )
        return cleaned_data


class CustomerPaymentForm(forms.ModelForm):
    class Meta:
        model = CustomerPayment
        fields = ['sale', 'customer', 'payment_date', 'amount', 'payment_method', 'reference_no', 'notes']
        widgets = {
            'payment_date': forms.DateInput(attrs={'type': 'date'}),
            'notes': forms.Textarea(attrs={'rows': 2}),
        }
