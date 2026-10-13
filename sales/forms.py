from decimal import Decimal

from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone

from books.models import Account
from core.phone import normalize_phone
from projects.models import Flat

from .models import CustomerPayment, FlatSale, HonorariumPayment, RefundPayment, Reference

DATE_WIDGET = forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d')


class FlatSaleForm(forms.ModelForm):
    """Book a flat for a customer.

    Sale value must be at least the total base price (base price, plus the parking price if the buyer
    takes the parking lot). Whatever the buyer pays above that is the honorarium for the reference.
    """

    class Meta:
        model = FlatSale
        fields = ['flat', 'customer', 'ref', 'sale_date', 'with_parking', 'sale_value', 'reg_value', 'notes']
        widgets = {
            'sale_date': DATE_WIDGET,
            'notes': forms.Textarea(attrs={'rows': 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['ref'].required = False
        self.fields['ref'].queryset = Reference.objects.all()
        self.fields['sale_value'].help_text = 'Pre-filled with the quoted price (plus parking if taken). It cannot be below the total base price.'
        if self.instance.pk:
            # The flat is fixed once the sale exists; changing it would leave the old flat marked booked/sold.
            self.fields['flat'].disabled = True
        else:
            self.fields['flat'].queryset = Flat.objects.filter(status=Flat.Status.AVAILABLE).select_related('project')
            self.fields['sale_date'].initial = timezone.localdate()

    def price_map(self):
        """Prices of every selectable flat's project, for the live total/honorarium preview."""
        flats = self.fields['flat'].queryset
        if self.instance.pk:
            flats = Flat.objects.filter(pk=self.instance.flat_id).select_related('project')
        data = {}
        sale = self.instance if self.instance.pk else None
        for flat in flats.select_related('project'):
            project = flat.project
            data[flat.pk] = {
                'base': str(sale.base_price if sale and sale.base_price else project.base_price),
                'quoted': str(project.quoted_price),
                'parking': str(sale.parking_price if sale and sale.parking_price else project.parking_price),
            }
        return data

    def clean(self):
        cleaned = super().clean()
        flat = cleaned.get('flat')
        if flat and not self.instance.pk:
            other = flat.sales.exclude(status=FlatSale.Status.CANCELLED).first()
            if other:
                raise ValidationError(
                    f'{flat} already has an active sale ({other.sale_no}). Cancel that sale first before selling this flat again.'
                )
        return cleaned


class SaleCancelForm(forms.Form):
    """Cancel a booking. The customer's money is returned at the agreed percentage, which can be below 100."""

    refund_percent = forms.DecimalField(
        min_value=Decimal('0'), max_value=Decimal('100'), decimal_places=2, initial=Decimal('100'),
        label='Refund percentage',
        help_text='Share of everything the customer has paid that is returned. The rest stays with the company.',
    )
    cancelled_on = forms.DateField(widget=DATE_WIDGET, label='Cancellation date')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['cancelled_on'].initial = timezone.localdate()


def _accounts():
    return Account.objects.filter(is_active=True)


class CustomerPaymentForm(forms.ModelForm):
    """Money received. Paying more than the net value is allowed; the extra is kept as the customer's balance."""

    class Meta:
        model = CustomerPayment
        fields = ['sale', 'payment_date', 'amount', 'account', 'reference_no', 'notes']
        widgets = {
            'payment_date': DATE_WIDGET,
            'notes': forms.Textarea(attrs={'rows': 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['sale'].queryset = FlatSale.objects.exclude(status=FlatSale.Status.CANCELLED).select_related('flat', 'customer')
        self.fields['sale'].label_from_instance = lambda sale: f'{sale.sale_no} - {sale.flat.flat_no} - {sale.customer.name}'
        self.fields['account'].queryset = _accounts()
        self.fields['account'].required = True
        self.fields['reference_no'].label = 'Cheque / transaction ref.'
        if not self.instance.pk:
            self.fields['payment_date'].initial = timezone.localdate()


class _PayoutForm(forms.ModelForm):
    """Money the company pays out against a sale, limited to what is still due."""

    def __init__(self, *args, sale=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.sale = sale
        self.fields['account'].queryset = _accounts()
        self.fields['date'].initial = timezone.localdate()
        self.fields['amount'].initial = self.due()

    def due(self):
        raise NotImplementedError

    def clean_amount(self):
        amount = self.cleaned_data['amount']
        due = self.due()
        if amount > due:
            raise ValidationError(f'Only {due:,.2f} is still due.')
        return amount

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.sale = self.sale
        if commit:
            instance.save()
        return instance


class HonorariumPaymentForm(_PayoutForm):
    class Meta:
        model = HonorariumPayment
        fields = ['date', 'amount', 'account', 'notes']
        widgets = {'date': DATE_WIDGET, 'notes': forms.TextInput()}

    def due(self):
        return self.sale.honorarium_due


class RefundPaymentForm(_PayoutForm):
    class Meta:
        model = RefundPayment
        fields = ['date', 'amount', 'account', 'notes']
        widgets = {'date': DATE_WIDGET, 'notes': forms.TextInput()}

    def due(self):
        return self.sale.refund_due


class ReferenceForm(forms.ModelForm):
    class Meta:
        model = Reference
        fields = ['name', 'phone', 'notes']
        widgets = {'notes': forms.Textarea(attrs={'rows': 2})}

    def clean_phone(self):
        return normalize_phone(self.cleaned_data.get('phone', ''))
