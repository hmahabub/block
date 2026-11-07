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

    flat_sale_value    what the customer agreed to pay for the flat itself
    parking_sale_value what the customer agreed to pay for the parking lot (0 when no parking is taken)
    sale_value      flat_sale_value + parking_sale_value: everything agreed for the flat and its parking
    total_base_price base price + parking price: what the company needs from the sale
    honorarium      sale_value - total_base_price: the extra the customer pays, passed on to the reference
                    (flat_honorarium + parking_honorarium)
    reg_value       registration cost incurred when the share is registered to the owner, borne by the customer
    net_value       sale_value + reg_value: everything the customer owes for this flat
    """

    class Status(models.TextChoices):
        BOOKED = 'BOOKED', 'Booked'
        REGISTERED = 'REGISTERED', 'Registered'
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
    sale_value = models.DecimalField(
        max_digits=14, decimal_places=2, default=0, validators=[MinValueValidator(0)],
        help_text='Flat sale value + parking sale value.',
    )
    parking_sale_value = models.DecimalField(
        max_digits=14, decimal_places=2, default=0, validators=[MinValueValidator(0)],
        help_text='What the customer pays for the parking lot (only when parking is taken). Part of the sale value.',
    )
    reg_value = models.DecimalField(
        'Reg value', max_digits=14, decimal_places=2, default=0, validators=[MinValueValidator(0)],
        help_text='Registration cost when the share is registered to the owner; paid by the customer.',
    )

    net_value = models.DecimalField(max_digits=14, decimal_places=2, default=0, editable=False)
    received_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0, editable=False)
    receivable_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0, editable=False)
    customer_balance = models.DecimalField(max_digits=14, decimal_places=2, default=0, editable=False)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.BOOKED)
    registered_on = models.DateField(
        null=True, blank=True, editable=False,
        help_text='The day the registry was completed and the flat registered to the owner.',
    )

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
    def flat_sale_value(self):
        """The part of the sale value that is for the flat itself."""
        return self.sale_value - self.parking_sale_value

    @property
    def honorarium(self):
        return max(self.sale_value - self.total_base_price, ZERO)

    @property
    def flat_honorarium(self):
        return max(self.flat_sale_value - self.base_price, ZERO)

    @property
    def parking_honorarium(self):
        return max(self.parking_sale_value - self.parking_price, ZERO) if self.with_parking else ZERO

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
        parking = (self.parking_price or self.flat.effective_parking_price) if self.with_parking else ZERO
        return base + parking

    def expected_prices(self):
        """(flat base price, parking price) this sale is measured against: its frozen prices, or the current ones."""
        project = self.flat.project
        base = self.base_price if self.base_price else project.base_price
        parking = (self.parking_price or self.flat.effective_parking_price) if self.with_parking else ZERO
        return base, parking

    def clean(self):
        if not self.flat_id or self.sale_value is None:
            return
        base, parking = self.expected_prices()
        errors = {}
        if self.flat_sale_value < base:
            errors['flat_sale_value'] = f'The flat sale value cannot be below the flat base price ({base:,.2f}).'
        if self.with_parking and self.parking_sale_value < parking:
            errors['parking_sale_value'] = f'The parking sale value cannot be below the parking price ({parking:,.2f}).'
        if errors:
            raise ValidationError(errors)

    def apply_snapshot_prices(self):
        """Freeze the project's prices on the sale so later price changes never alter it."""
        project = self.flat.project
        if not self.base_price:
            self.base_price = project.base_price
        self.parking_price = self.flat.effective_parking_price if self.with_parking else ZERO

    def register(self, on=None):
        """The registry is completed: the flat is registered to the owner."""
        self.registered_on = on or timezone.localdate()

    def undo_registry(self):
        self.registered_on = None

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
            self.status = self.Status.REGISTERED if self.registered_on else self.Status.BOOKED
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
            self.parking_price = self.flat.effective_parking_price
        if not self.with_parking:
            self.parking_sale_value = ZERO
        elif not self.parking_sale_value and self.parking_price:
            # A sale entered as one total: take the parking lot at its price, the rest is the flat.
            self.parking_sale_value = min(self.parking_price, self.sale_value)
        self.recompute()
        adding = self._state.adding
        super().save(*args, **kwargs)
        if adding:
            Invoice.objects.get_or_create(sale=self, kind=Invoice.Kind.BOOKING)   # every flat booking has one invoice
        self._sync_flat_status()

    def _sync_flat_status(self):
        """A flat is Sold while it has an active sale, and Available again once that sale is cancelled."""
        from projects.models import Flat

        flat = self.flat
        active = flat.sales.exclude(status=self.Status.CANCELLED)
        if not active.exists():
            new_status = Flat.Status.AVAILABLE
        elif active.filter(status=self.Status.REGISTERED).exists():
            new_status = Flat.Status.REGISTERED
        else:
            new_status = Flat.Status.BOOKED
        if flat.status != new_status:
            flat.status = new_status
            flat.save(update_fields=['status'])

    @property
    def booking_invoice(self):
        invoice, _ = Invoice.objects.get_or_create(sale=self, kind=Invoice.Kind.BOOKING)
        return invoice

    @property
    def honorarium_voucher_no(self):
        """Every booking has one honorarium voucher; the payments to the reference are made under it."""
        return f'HV-{self.pk:05d}'

    def recalc_received_amount(self):
        total = self.payments.aggregate(total=models.Sum('amount'))['total'] or ZERO
        self.received_amount = total
        self.save()


class Invoice(models.Model):
    """What a customer is asked to pay: one invoice for every flat booking, and one for every installment issued on it.

    The booking invoice is the net value less the installments carved out of it, so the invoices of a booking always add up
    to its net value. Customers pay under an invoice: every payment is recorded against one."""

    class Kind(models.TextChoices):
        BOOKING = 'BOOKING', 'Flat booking'
        INSTALLMENT = 'INSTALLMENT', 'Installment'

    sale = models.ForeignKey(FlatSale, on_delete=models.CASCADE, related_name='invoices')
    kind = models.CharField(max_length=12, choices=Kind.choices)
    charge = models.OneToOneField(
        'installments.InstallmentCharge', null=True, blank=True, on_delete=models.CASCADE, related_name='invoice',
    )
    issued_on = models.DateField(default=timezone.localdate)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['issued_on', 'id']
        constraints = [
            models.UniqueConstraint(fields=['sale'], condition=models.Q(kind='BOOKING'), name='one_booking_invoice_per_sale'),
        ]

    def __str__(self):
        return f'{self.number} ({self.label})'

    @property
    def number(self):
        return f'INV-{self.pk:05d}'

    def get_absolute_url(self):
        return reverse('sales:invoice-detail', kwargs={'pk': self.pk})

    @property
    def label(self):
        if self.kind == self.Kind.INSTALLMENT and self.charge_id:
            return self.charge.installment.title
        return self.get_kind_display()

    @property
    def total(self):
        if self.kind == self.Kind.INSTALLMENT:
            return self.charge.amount if self.charge_id else ZERO
        scheduled = sum((c.amount for c in self.sale.installment_charges.all()), ZERO)
        return max(self.sale.net_value - scheduled, ZERO)

    @property
    def paid(self):
        return sum((p.amount for p in self.payments.all()), ZERO)

    @property
    def due(self):
        return max(self.total - self.paid, ZERO)

    @property
    def due_date(self):
        return self.charge.installment.due_date if self.kind == self.Kind.INSTALLMENT and self.charge_id else None

    @property
    def status(self):
        if self.sale.status == FlatSale.Status.CANCELLED:
            return 'Cancelled'
        if self.due <= 0:
            return 'Paid'
        if self.due_date and self.due_date < timezone.localdate():
            return 'Overdue'
        return 'Partly paid' if self.paid > 0 else 'Due'


class CustomerPayment(ConfirmableModel):
    """Money received from a customer, always under one of the customer's invoices."""

    class Method(models.TextChoices):
        CASH = 'CASH', 'Cash'
        BANK = 'BANK', 'Bank'
        CHEQUE = 'CHEQUE', 'Cheque'
        OTHER = 'OTHER', 'Other'

    sale = models.ForeignKey(FlatSale, on_delete=models.CASCADE, related_name='payments')
    customer = models.ForeignKey('customers.Customer', on_delete=models.PROTECT, related_name='payments')
    invoice = models.ForeignKey(
        Invoice, on_delete=models.RESTRICT, related_name='payments', verbose_name='Paid under invoice',
        help_text='The invoice this payment settles: the flat booking, or an installment.',
    )
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
    def purpose_text(self):
        """What the payment was for, in words: Flat booking, or the installment it paid."""
        return self.invoice.label

    @property
    def receipt_no(self):
        return f'MR-{self.pk:05d}'

    def __str__(self):
        return f'{self.customer} - {self.amount} ({self.payment_date})'

    def save(self, *args, **kwargs):
        if not self.invoice_id and self.sale_id:
            self.invoice = self.sale.booking_invoice        # a payment with no invoice named settles the flat booking
        if self.invoice_id and not self.sale_id:
            self.sale = self.invoice.sale
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
