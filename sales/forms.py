from django import forms

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
        if not self.instance.pk:
            self.fields['flat'].queryset = self.fields['flat'].queryset.filter(
                status__in=['AVAILABLE', 'BOOKED']
            )


class CustomerPaymentForm(forms.ModelForm):
    class Meta:
        model = CustomerPayment
        fields = ['sale', 'customer', 'payment_date', 'amount', 'payment_method', 'reference_no', 'notes']
        widgets = {
            'payment_date': forms.DateInput(attrs={'type': 'date'}),
            'notes': forms.Textarea(attrs={'rows': 2}),
        }
