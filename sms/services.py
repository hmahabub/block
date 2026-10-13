"""Customer SMS: one on every payment received, and balance reminders only when a user sends them."""
import datetime
from decimal import Decimal

from .backends import SmsError, get_backend
from .models import SmsLog

ZERO = Decimal('0')


def _company():
    from core.models import CompanyProfile

    return CompanyProfile.current().display_name


def _amount(value):
    return f'Tk {Decimal(value):,.2f}'


def _day(value):
    """dd-mm-yyyy, whether the model still holds the date the caller assigned as text or as a date."""
    if isinstance(value, str):
        value = datetime.date.fromisoformat(value)
    return f'{value:%d-%m-%Y}'


def deliver(customer, message, kind, user=None):
    """Send one SMS to the customer and record the result. Never raises: a gateway problem must never
    stop a payment from being saved. Returns the SmsLog, or None if the customer is excluded."""
    if not customer.sms_enabled or not customer.phone:
        return None
    backend = get_backend()
    status, error = SmsLog.Status.SENT if backend.delivers else SmsLog.Status.LOGGED, ''
    try:
        backend.send(customer.phone, message)
    except SmsError as exc:
        status, error = SmsLog.Status.FAILED, str(exc)[:300]
    except Exception as exc:  # noqa: BLE001 - any gateway fault is recorded, never raised
        status, error = SmsLog.Status.FAILED, f'{type(exc).__name__}: {exc}'[:300]
    return SmsLog.objects.create(
        customer=customer, phone=customer.phone, kind=kind, message=message, status=status, error=error, sent_by=user,
    )


def payment_message(payment):
    sale = payment.sale
    text = (
        f'Dear {payment.customer.display_name}, we received {_amount(payment.amount)} on {_day(payment.payment_date)} '
        f'for flat {sale.flat.flat_no}, {sale.project.project_name}. Receipt {payment.receipt_no}. '
        f'Total paid {_amount(sale.received_amount)}'
    )
    if sale.receivable_amount > 0:
        text += f', balance due {_amount(sale.receivable_amount)}.'
    elif sale.customer_balance > 0:
        text += f'; your credit balance is {_amount(sale.customer_balance)}.'
    else:
        text += '; fully paid.'
    return f'{text} - {_company()}'


def notify_payment(payment, user=None):
    """SMS on every payment received (skipped for customers excluded from SMS)."""
    return deliver(payment.customer, payment_message(payment), SmsLog.Kind.PAYMENT, user)


def customer_statement(customer):
    """Open bookings of a customer with what is still due on each."""
    rows = []
    for sale in customer.sales.exclude(status='CANCELLED').select_related('flat', 'project'):
        rows.append({
            'sale': sale, 'net': sale.net_value, 'received': sale.received_amount,
            'due': sale.receivable_amount, 'credit': sale.customer_balance,
        })
    return rows


def reminder_message(customer):
    rows = [row for row in customer_statement(customer) if row['due'] > 0]
    if not rows:
        return ''
    parts = '; '.join(f'flat {r["sale"].flat.flat_no} ({r["sale"].project.project_name}): {_amount(r["due"])}' for r in rows)
    total = sum((r['due'] for r in rows), ZERO)
    return (
        f'Dear {customer.display_name}, a friendly reminder: balance due {_amount(total)} - {parts}. '
        f'Please pay at your earliest. Ignore if already paid. - {_company()}'
    )


def customers_with_dues():
    """Customers with something still due, for the reminder screen."""
    from customers.models import Customer

    result = []
    for customer in Customer.objects.prefetch_related('sales').order_by('name'):
        due = sum((s.receivable_amount for s in customer.sales.all() if s.status != 'CANCELLED'), ZERO)
        if due > 0:
            customer.total_due = due
            result.append(customer)
    return result


def send_reminders(customers, user):
    """Send a balance reminder to each customer (excluded customers and customers with nothing due are skipped)."""
    sent, skipped = [], []
    for customer in customers:
        message = reminder_message(customer)
        log = deliver(customer, message, SmsLog.Kind.REMINDER, user) if message else None
        (sent if log else skipped).append(customer)
    return sent, skipped


def backend_description():
    name = get_backend().name
    if name == 'http':
        return 'Live gateway (http)'
    return 'No gateway configured - messages are only recorded in the log'
