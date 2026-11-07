from decimal import Decimal

from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone

from books.models import Account
from core.phone import normalize_phone
from projects.models import Flat

from .models import CustomerPayment, FlatSale, HonorariumPayment, Invoice, RefundPayment, Reference

DATE_WIDGET = forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d')


class FlatSaleForm(forms.ModelForm):
    """Book a flat for a customer.

    The flat and the parking lot have each their own sale value: the flat sale value cannot be below the flat's base
    price, and the parking sale value cannot be below the parking price. The sale value is the two added together, and
    whatever the buyer pays above the total base price is the honorarium for the reference.
    """

    flat_sale_value = forms.DecimalField(
        label='Flat sale value', min_value=Decimal('0'), max_digits=14, decimal_places=2,
        help_text='What the customer pays for the flat itself. Pre-filled with the quoted price; not below the flat base price.',
    )

    field_order = ['flat', 'customer', 'ref', 'sale_date', 'with_parking', 'flat_sale_value', 'parking_sale_value', 'reg_value', 'notes']

    class Meta:
        model = FlatSale
        fields = ['flat', 'customer', 'ref', 'sale_date', 'with_parking', 'parking_sale_value', 'reg_value', 'notes']
        widgets = {
            'sale_date': DATE_WIDGET,
            'notes': forms.Textarea(attrs={'rows': 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['ref'].required = False
        self.fields['ref'].queryset = Reference.objects.all()
        self.fields['parking_sale_value'].required = False
        self.fields['parking_sale_value'].label = 'Parking sale value'
        self.fields['parking_sale_value'].help_text = (
            'What the customer pays for the parking lot, when parking is taken. Pre-filled with the parking price; not below it.')
        if self.instance.pk:
            self.initial['flat_sale_value'] = self.instance.flat_sale_value
            # The flat is fixed once the sale exists; changing it would leave the old flat marked sold.
            self.fields['flat'].disabled = True
        else:
            self.fields['flat'].queryset = Flat.objects.filter(status=Flat.Status.AVAILABLE).select_related('project')
            self.fields['sale_date'].initial = timezone.localdate()

    def price_map(self, include_base=True):
        """Prices of every selectable flat's project, for the live total/honorarium preview.

        The base price is left out unless `include_base`, so it is not even in the page source while screens are locked."""
        flats = self.fields['flat'].queryset
        if self.instance.pk:
            flats = Flat.objects.filter(pk=self.instance.flat_id).select_related('project')
        data = {}
        sale = self.instance if self.instance.pk else None
        for flat in flats.select_related('project'):
            project = flat.project
            data[flat.pk] = {
                'quoted': str(project.quoted_price),
                'parking': str(sale.parking_price if sale and sale.parking_price else flat.effective_parking_price),
            }
            if include_base:
                data[flat.pk]['base'] = str(sale.base_price if sale and sale.base_price else project.base_price)
        return data

    def clean(self):
        cleaned = super().clean()
        flat_value, parking_value = cleaned.get('flat_sale_value'), cleaned.get('parking_sale_value')
        if not cleaned.get('with_parking'):
            parking_value = Decimal('0')
        elif parking_value is None:
            # parking taken but no value typed: the parking lot is sold at its price
            flat = cleaned.get('flat')
            parking_value = (self.instance.parking_price or flat.effective_parking_price) if flat else Decimal('0')
        cleaned['parking_sale_value'] = parking_value
        if flat_value is not None:
            self.instance.sale_value = flat_value + parking_value
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
    """A customer's payment, recorded from the invoice it pays: the flat booking's, or an installment's.

    It can be for no more than what is still due on that invoice."""

    class Meta:
        model = CustomerPayment
        fields = ['invoice', 'payment_date', 'amount', 'account', 'reference_no', 'notes']
        widgets = {
            'payment_date': DATE_WIDGET,
            'notes': forms.Textarea(attrs={'rows': 2}),
        }

    field_order = ['invoice', 'payment_date', 'amount', 'account', 'reference_no', 'notes']

    def __init__(self, *args, development=None, invoice=None, **kwargs):
        super().__init__(*args, **kwargs)
        invoices = Invoice.objects.exclude(sale__status=FlatSale.Status.CANCELLED).select_related(
            'sale', 'sale__customer', 'sale__flat', 'sale__project', 'charge', 'charge__installment',
        ).order_by('sale__customer__name', 'sale__flat__flat_no', 'issued_on', 'id')
        if development is not None:
            invoices = invoices.filter(sale__project__development=development)
        self.fields['invoice'].queryset = invoices
        self.fields['invoice'].label_from_instance = self.invoice_label
        self.fields['invoice'].empty_label = 'Choose the invoice being paid...'
        if invoice is not None:
            # Opened from an invoice: the payment is for that invoice and no other.
            self.fields['invoice'].queryset = invoices.filter(pk=invoice.pk)
            self.fields['invoice'].disabled = True
            self.initial['invoice'] = invoice.pk
            self.fields['amount'].initial = invoice.due or None
        self.fields['account'].queryset = _accounts()
        self.fields['account'].required = True
        self.fields['reference_no'].label = 'Cheque / transaction ref.'
        if not self.instance.pk:
            self.fields['payment_date'].initial = timezone.localdate()

    @staticmethod
    def invoice_label(invoice):
        sale = invoice.sale
        due = f'due {invoice.due:,.2f}' + (f' by {invoice.due_date:%d %b %Y}' if invoice.due_date else '')
        return f'{invoice.number} - {sale.customer.name} - {sale.project.project_name} / {sale.flat.flat_no} - {invoice.label} ({due})'

    def clean(self):
        cleaned = super().clean()
        invoice, amount = cleaned.get('invoice'), cleaned.get('amount')
        if invoice is not None:
            due = invoice.due
            if due <= 0:
                self.add_error('invoice', f'{invoice.number} is already paid in full.')
            elif amount is not None and amount > due:
                self.add_error('amount', f'Only {due:,.2f} is still due on {invoice.number}; the payment cannot be more than that.')
        return cleaned

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.sale = instance.invoice.sale
        if commit:
            instance.save()
        return instance


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
