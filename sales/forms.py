from django import forms
from django.core.exceptions import ValidationError

from .models import CustomerPayment, FlatSale


class FlatSaleForm(forms.ModelForm):
    cancel_sale = forms.BooleanField(
        required=False,
        label='Cancel this sale',
        help_text='Cancelling frees the flat so it can be sold to someone else.',
    )

    class Meta:
        model = FlatSale
        fields = [
            'flat', 'customer', 'sale_date', 'base_price',
            'other_charges', 'discount', 'notes',
        ]
        widgets = {
            'sale_date': forms.DateInput(attrs={'type': 'date'}),
            'notes': forms.Textarea(attrs={'rows': 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            # The flat is fixed once the sale exists; changing it would leave the
            # old flat marked as booked/sold.
            self.fields['flat'].disabled = True
            self.fields['cancel_sale'].initial = self.instance.status == FlatSale.Status.CANCELLED
        else:
            del self.fields['cancel_sale']
            self.fields['flat'].queryset = self.fields['flat'].queryset.filter(status='AVAILABLE')

    def clean(self):
        cleaned_data = super().clean()
        flat = cleaned_data.get('flat')
        if flat and not cleaned_data.get('cancel_sale'):
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

    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.cleaned_data.get('cancel_sale'):
            instance.status = FlatSale.Status.CANCELLED
        elif instance.status == FlatSale.Status.CANCELLED:
            # Un-cancelling: FlatSale.save() recomputes Booked/Sold from payments.
            instance.status = FlatSale.Status.BOOKED
        if commit:
            instance.save()
        return instance


class CustomerPaymentForm(forms.ModelForm):
    class Meta:
        model = CustomerPayment
        fields = ['sale', 'customer', 'payment_date', 'amount', 'payment_method', 'reference_no', 'notes']
        widgets = {
            'payment_date': forms.DateInput(attrs={'type': 'date'}),
            'notes': forms.Textarea(attrs={'rows': 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['sale'].queryset = self.fields['sale'].queryset.exclude(status=FlatSale.Status.CANCELLED)
