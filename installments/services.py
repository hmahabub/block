"""Working out, issuing and tracking installments.

The rules, in one place:

* Everyone who booked a flat in the project (cancelled sales excluded) is charged, in every building or in the one chosen.
* The amount is the same for every flat, or a percentage of each sale value. It is never more than what the booking still
  has left to schedule: net value, less what was paid under the booking invoice, less the installments already issued.
* Every installment issued to a booking is an **invoice** of its own (sales.Invoice). The customer pays under that invoice,
  and what has been paid under it is what has been paid on the installment. A payment under the booking invoice never
  pays an installment.
"""
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from sales.models import CustomerPayment, FlatSale, Invoice
from sms.models import SmsLog
from sms.services import _day, _sale_values, deliver
from sms.templating import money, render

from .models import Installment, InstallmentCharge

ZERO = Decimal('0')
CENT = Decimal('0.01')

PAID, PART, DUE, OVERDUE = 'Paid', 'Partly paid', 'Due', 'Overdue'


@dataclass
class ChargeRow:
    charge: InstallmentCharge
    paid: Decimal
    due: Decimal
    status: str

    @property
    def installment(self):
        return self.charge.installment

    @property
    def sale(self):
        return self.charge.sale

    @property
    def invoice(self):
        return self.charge.invoice


def _status(charge, paid, today):
    if paid >= charge.amount:
        return PAID
    if charge.installment.due_date < today:
        return OVERDUE
    return PART if paid > 0 else DUE


def paid_by_invoice(payments):
    """{invoice id: total paid under it} for a list of payments."""
    totals = {}
    for payment in payments:
        totals[payment.invoice_id] = totals.get(payment.invoice_id, ZERO) + payment.amount
    return totals


def allocate(sale, charges=None, payments=None, today=None):
    """Each of the sale's installment charges with what has been paid under its invoice, earliest deadline first."""
    today = today or timezone.localdate()
    if charges is None:
        charges = list(sale.installment_charges.select_related('installment', 'invoice'))
    if payments is None:
        payments = list(sale.payments.all())
    charges = sorted(charges, key=lambda c: (c.installment.due_date, c.installment.number, c.pk))
    totals = paid_by_invoice(payments)
    rows = []
    for charge in charges:
        invoice = getattr(charge, 'invoice', None)
        paid = min(totals.get(invoice.pk, ZERO), charge.amount) if invoice else ZERO
        rows.append(ChargeRow(charge, paid, charge.amount - paid, _status(charge, paid, today)))
    return rows


def rows_for(development, installment=None, building=None):
    """Allocated charge rows of every active booking in the project (or of one installment), in one pass."""
    charges = (
        InstallmentCharge.objects.filter(installment__development=development)
        .exclude(sale__status=FlatSale.Status.CANCELLED)
        .select_related('installment', 'invoice', 'sale', 'sale__customer', 'sale__flat', 'sale__project')
    )
    if building:
        charges = charges.filter(sale__project=building)
    by_sale = {}
    for charge in charges:
        by_sale.setdefault(charge.sale_id, []).append(charge)
    payments = {}
    for payment in CustomerPayment.objects.filter(sale_id__in=by_sale):
        payments.setdefault(payment.sale_id, []).append(payment)
    rows = []
    for sale_id, sale_charges in by_sale.items():
        rows += allocate(sale_charges[0].sale, sale_charges, payments.get(sale_id, []))
    if installment:
        rows = [r for r in rows if r.charge.installment_id == installment.pk]
    rows.sort(key=lambda r: (r.installment.due_date, r.installment.number, r.sale.customer.name, r.sale.sale_no))
    return rows


def due_total(rows):
    return sum((r.due for r in rows), ZERO)


def overdue_total(rows):
    return sum((r.due for r in rows if r.status == OVERDUE), ZERO)


def sale_installments(sale):
    """The sale's own installment rows, for its page."""
    return allocate(sale)


def customer_due(customer, development=None):
    """(due, overdue) across the customer's active bookings (only those in `development`, when given)."""
    sales = customer.sales.exclude(status=FlatSale.Status.CANCELLED).select_related('project')
    if development is not None:
        sales = sales.filter(project__development=development)
    due = overdue = ZERO
    for sale in sales.prefetch_related('installment_charges__installment', 'installment_charges__invoice', 'payments'):
        rows = allocate(sale, list(sale.installment_charges.all()), list(sale.payments.all()))
        due += due_total(rows)
        overdue += overdue_total(rows)
    return due, overdue


# --- issuing ------------------------------------------------------------------
def eligible_sales(development, building=None):
    sales = (
        FlatSale.objects.filter(project__development=development)
        .exclude(status=FlatSale.Status.CANCELLED)
        .select_related('customer', 'flat', 'project').order_by('project__project_name', 'flat__flat_no')
    )
    return sales.filter(project=building) if building else sales


def left_to_schedule(sale):
    """What the booking can still be charged: net value, less what was paid under the booking invoice, less installments issued."""
    booking = next((i for i in sale.invoices.all() if i.kind == Invoice.Kind.BOOKING), None)
    booking_paid = sum((p.amount for p in sale.payments.all() if booking and p.invoice_id == booking.pk), ZERO)
    scheduled = sum((c.amount for c in sale.installment_charges.all()), ZERO)
    return max(sale.net_value - booking_paid - scheduled, ZERO)


def planned_amount(basis, value, sale):
    if basis == Installment.Basis.PERCENT:
        return (sale.sale_value * value / Decimal(100)).quantize(CENT, ROUND_HALF_UP)
    return value


def preview(development, building, basis, value):
    """Who would be charged how much. Returns (rows, skipped): rows are (sale, amount, capped), skipped are (sale, reason)."""
    rows, skipped = [], []
    sales = eligible_sales(development, building).prefetch_related('installment_charges', 'payments', 'invoices')
    for sale in sales:
        left = left_to_schedule(sale)
        planned = planned_amount(basis, value, sale)
        if left <= 0:
            skipped.append((sale, 'Nothing left to charge: the whole amount is already scheduled or paid.'))
        elif planned <= 0:
            skipped.append((sale, 'The amount works out to nothing.'))
        else:
            rows.append((sale, min(planned, left), planned > left))
    return rows, skipped


@transaction.atomic
def issue(development, user, title, due_date, basis, value, building=None, notes=''):
    """Create the installment, charge every eligible booking and issue each its invoice.

    Returns the Installment (with `.issued_charges`)."""
    rows, skipped = preview(development, building, basis, value)
    number = (Installment.objects.filter(development=development).aggregate(top=Max('number'))['top'] or 0) + 1
    installment = Installment.objects.create(
        development=development, building=building, number=number, title=title, due_date=due_date, basis=basis, value=value,
        notes=notes, issued_by=user, issued_on=timezone.localdate(),
    )
    charges = []
    for sale, amount, _ in rows:
        charge = InstallmentCharge.objects.create(installment=installment, sale=sale, amount=amount)
        Invoice.objects.create(sale=sale, kind=Invoice.Kind.INSTALLMENT, charge=charge, issued_on=installment.issued_on)
        charges.append(charge)
    installment.issued_charges = charges
    installment.skipped = skipped
    return installment


@transaction.atomic
def withdraw(installment):
    """Take back an installment nobody has paid anything towards (its invoices go with it). False when someone already has."""
    rows = rows_for(installment.development, installment)
    if any(r.paid > 0 for r in rows):
        return False
    installment.delete()
    return True


# --- the SMS -------------------------------------------------------------------
def installment_message(charge):
    sale = charge.sale
    rows = allocate(sale)
    return render('INSTALLMENT', {
        **_sale_values(sale), 'installment': charge.installment.title, 'amount': money(charge.amount),
        'deadline': _day(charge.installment.due_date), 'installment_due': money(due_total(rows)),
    })


def notify_installment(charge, user=None):
    """SMS the customer what is due and by when. Returns the SmsLog (None when the customer is excluded from SMS)."""
    log = deliver(
        charge.sale.customer, installment_message(charge), SmsLog.Kind.INSTALLMENT, user,
        reference=f'INST-{charge.installment.number}-{charge.sale.sale_no}',
    )
    if log is not None:
        InstallmentCharge.objects.filter(pk=charge.pk).update(notified_at=timezone.now())
    return log


def notify_all(charges, user=None):
    """SMS every charge; returns {status: count} plus 'EXCLUDED' for customers who opted out of SMS."""
    counts = {}
    for charge in charges:
        log = notify_installment(charge, user)
        key = log.status if log else 'EXCLUDED'
        counts[key] = counts.get(key, 0) + 1
    return counts
