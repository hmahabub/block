from decimal import ROUND_HALF_UP, Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models
from django.urls import reverse
from django.utils import timezone

from core.models import ConfirmableModel
from core.numbering import generate_slash_code

ZERO = Decimal('0')
CENT = Decimal('0.01')

phone_regex = RegexValidator(
    regex=r'^\+?\d{9,15}$', message="Phone number must be like +8801711000000 or 01711000000.",
)


class Reference(models.Model):
    """The person who referred a buyer and receives the honorarium on the sale."""

    name = models.CharField(max_length=150)
    phone = models.CharField(max_length=17, blank=True, validators=[phone_regex])
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']
        verbose_name = 'Reference'

    def __str__(self):
        return f'{self.name} ({self.phone})' if self.phone else self.name

    def get_absolute_url(self):
        return reverse('sales:reference-detail', kwargs={'pk': self.pk})


class FlatSale(models.Model):
    """A flat share sold to a customer.

    sale_value      what the customer actually agreed to pay for the flat (and parking, if taken)
    total_base_price base price + parking price: what the company needs from the sale
    honorarium      sale_value - total_base_price: the extra the customer pays, passed on to the reference
    reg_value       registration cost incurred when the share is registered to the owner, borne by the customer
    net_value       sale_value + reg_value: everything the customer owes for this flat
    """

    class Status(models.TextChoices):
        SOLD = 'SOLD', 'Sold'
        CANCELLED = 'CANCELLED', 'Cancelled'

    sale_no = models.CharField(max_length=30, unique=True, editable=False)
    project = models.ForeignKey('projects.Project', on_delete=models.CASCADE, related_name='sales')
    flat = models.ForeignKey('projects.Flat', on_delete=models.PROTECT, related_name='sales')
    customer = models.ForeignKey('customers.Customer', on_delete=models.PROTECT, related_name='sales')
    ref = models.ForeignKey(
        Reference, null=True, blank=True, on_delete=models.SET_NULL, related_name='sales',
        verbose_name='Ref', help_text='The reference who receives the honorarium.',
    )
    sale_date = models.DateField()

    with_parking = models.BooleanField('Includes parking lot', default=False)
    base_price = models.DecimalField(max_digits=14, decimal_places=2, validators=[MinValueValidator(0)])
    parking_price = models.DecimalField(max_digits=14, decimal_places=2, default=0, editable=False)
    sale_value = models.DecimalField(max_digits=14, decimal_places=2, default=0, validators=[MinValueValidator(0)])
    reg_value = models.DecimalField(
        'Reg value', max_digits=14, decimal_places=2, default=0, validators=[MinValueValidator(0)],
        help_text='Registration cost when the share is registered to the owner; paid by the customer.',
    )

    net_value = models.DecimalField(max_digits=14, decimal_places=2, default=0, editable=False)
    received_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0, editable=False)
    receivable_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0, editable=False)
    customer_balance = models.DecimalField(max_digits=14, decimal_places=2, default=0, editable=False)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.SOLD)

    cancelled_on = models.DateField(null=True, blank=True, editable=False)
    refund_percent = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True, editable=False,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )
    refund_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0, editable=False)

    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-sale_date', '-id']
        verbose_name = 'Flat Sale'

    def __str__(self):
        return f'{self.sale_no} - {self.flat}'

    def get_absolute_url(self):
        return reverse('sales:detail', kwargs={'pk': self.pk})

    # --- the money ---------------------------------------------------------------
    @property
    def total_base_price(self):
        return self.base_price + self.parking_price

    @property
    def honorarium(self):
        return max(self.sale_value - self.total_base_price, ZERO)

    @property
    def honorarium_paid(self):
        return self.honorarium_payments.aggregate(total=models.Sum('amount'))['total'] or ZERO

    @property
    def honorarium_due(self):
        if self.status == self.Status.CANCELLED:
            return ZERO
        return max(self.honorarium - self.honorarium_paid, ZERO)

    @property
    def refund_paid(self):
        return self.refund_payments.aggregate(total=models.Sum('amount'))['total'] or ZERO

    @property
    def refund_due(self):
        return max(self.refund_amount - self.refund_paid, ZERO) if self.status == self.Status.CANCELLED else ZERO

    @property
    def retained_on_cancellation(self):
        """Money kept by the company when a booking is cancelled for less than a full refund."""
        if self.status != self.Status.CANCELLED:
            return ZERO
        return self.received_amount - self.refund_amount

    def expected_total_base_price(self):
        """Total base price for this sale: its frozen prices, or the project's current ones for a new sale."""
        if not self.flat_id:
            return None
        project = self.flat.project
        base = self.base_price if self.base_price else project.base_price
        parking = (self.parking_price or project.parking_price) if self.with_parking else ZERO
        return base + parking

    def clean(self):
        total_base = self.expected_total_base_price()
        if total_base is not None and self.sale_value is not None and self.sale_value < total_base:
            raise ValidationError({
                'sale_value': f'The sale value cannot be below the total base price ({total_base:,.2f}).'
            })

    def apply_snapshot_prices(self):
        """Freeze the project's prices on the sale so later price changes never alter it."""
        project = self.flat.project
        if not self.base_price:
            self.base_price = project.base_price
        self.parking_price = project.parking_price if self.with_parking else ZERO

    def cancel(self, refund_percent):
        self.status = self.Status.CANCELLED
        self.cancelled_on = self.cancelled_on or timezone.localdate()
        self.refund_percent = Decimal(refund_percent)
        self.refund_amount = (self.received_amount * self.refund_percent / Decimal(100)).quantize(CENT, ROUND_HALF_UP)

    def recompute(self):
        """Recalculate every derived amount. A sale is Sold from the moment it is made, until it is cancelled."""
        self.net_value = self.sale_value + self.reg_value
        self.receivable_amount = max(self.net_value - self.received_amount, ZERO)
        self.customer_balance = max(self.received_amount - self.net_value, ZERO)
        if self.status != self.Status.CANCELLED:
            self.status = self.Status.SOLD
        else:
            self.refund_amount = (self.received_amount * (self.refund_percent or ZERO) / Decimal(100)).quantize(CENT, ROUND_HALF_UP)

    def save(self, *args, **kwargs):
        if not self.sale_no:
            self.sale_no = generate_slash_code('sale')
        if not self.project_id and self.flat_id:
            self.project = self.flat.project
        if self._state.adding or not self.base_price:
            self.apply_snapshot_prices()
        elif not self.with_parking:
            self.parking_price = ZERO
        elif not self.parking_price:
            self.parking_price = self.flat.project.parking_price
        self.recompute()
        super().save(*args, **kwargs)
        self._sync_flat_status()

    def _sync_flat_status(self):
        """A flat is Sold while it has an active sale, and Available again once that sale is cancelled."""
        from projects.models import Flat

        flat = self.flat
        active = flat.sales.exclude(status=self.Status.CANCELLED)
        new_status = Flat.Status.SOLD if active.exists() else Flat.Status.AVAILABLE
        if flat.status != new_status:
            flat.status = new_status
            flat.save(update_fields=['status'])

    def recalc_received_amount(self):
        total = self.payments.aggregate(total=models.Sum('amount'))['total'] or ZERO
        self.received_amount = total
        self.save()


class CustomerPayment(ConfirmableModel):
    """Money received from a customer. Anything beyond the net value becomes the customer's balance."""

    class Method(models.TextChoices):
        CASH = 'CASH', 'Cash'
        BANK = 'BANK', 'Bank'
        CHEQUE = 'CHEQUE', 'Cheque'
        OTHER = 'OTHER', 'Other'

    sale = models.ForeignKey(FlatSale, on_delete=models.CASCADE, related_name='payments')
    customer = models.ForeignKey('customers.Customer', on_delete=models.PROTECT, related_name='payments')
    account = models.ForeignKey(
        'books.Account', null=True, blank=True, on_delete=models.PROTECT, related_name='customer_payments',
        verbose_name='Received into', help_text='The bank or cash account the money went into.',
    )
    payment_date = models.DateField()
    amount = models.DecimalField(max_digits=14, decimal_places=2, validators=[MinValueValidator(0.01)])
    payment_method = models.CharField(max_length=10, choices=Method.choices, default=Method.BANK)
    reference_no = models.CharField(max_length=100, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-payment_date', '-id']
        verbose_name = 'Customer Payment'

    @property
    def receipt_no(self):
        return f'MR-{self.pk:05d}'

    def __str__(self):
        return f'{self.customer} - {self.amount} ({self.payment_date})'

    def save(self, *args, **kwargs):
        if not self.customer_id and self.sale_id:
            self.customer = self.sale.customer
        if self.account_id:
            self.payment_method = self.Method.CASH if self.account.is_cash else self.Method.BANK
        super().save(*args, **kwargs)
        self.sale.recalc_received_amount()

    def delete(self, *args, **kwargs):
        sale = self.sale
        super().delete(*args, **kwargs)
        sale.recalc_received_amount()


class _SalePayout(ConfirmableModel):
    """Common shape of money the company pays out against a sale."""

    date = models.DateField()
    amount = models.DecimalField(max_digits=14, decimal_places=2, validators=[MinValueValidator(0.01)])
    notes = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True
        ordering = ['-date', '-id']


class HonorariumPayment(_SalePayout):
    """Honorarium paid to the reference for a sale."""

    sale = models.ForeignKey(FlatSale, on_delete=models.CASCADE, related_name='honorarium_payments')
    account = models.ForeignKey('books.Account', on_delete=models.PROTECT, related_name='honorarium_payments',
                                verbose_name='Paid from', help_text='The bank or cash account the money was paid from.')

    class Meta(_SalePayout.Meta):
        verbose_name = 'Honorarium Payment'

    @property
    def reference_no(self):
        return f'HP-{self.pk:05d}'

    def __str__(self):
        return f'{self.reference_no}: {self.amount} to {self.sale.ref or "ref"}'


class RefundPayment(_SalePayout):
    """Money returned to a customer after a booking was cancelled."""

    sale = models.ForeignKey(FlatSale, on_delete=models.CASCADE, related_name='refund_payments')
    account = models.ForeignKey('books.Account', on_delete=models.PROTECT, related_name='refund_payments',
                                verbose_name='Paid from', help_text='The bank or cash account the money was paid from.')

    class Meta(_SalePayout.Meta):
        verbose_name = 'Refund Payment'

    @property
    def reference_no(self):
        return f'RF-{self.pk:05d}'

    def __str__(self):
        return f'{self.reference_no}: {self.amount} to {self.sale.customer}'
