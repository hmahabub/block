"""Customer SMS: one when a flat is booked, one on every payment received, and balance reminders only when a user
sends them. The wording of each is a template in .env (see sms.templating)."""
import datetime
from decimal import Decimal

from .backends import SmsError, get_backend
from .models import SmsLog
from .templating import money, render

ZERO = Decimal('0')


def _company():
    from core.models import CompanyProfile

    return CompanyProfile.current().display_name


def _day(value):
    """dd-mm-yyyy, whether the model still holds the date the caller assigned as text or as a date."""
    if isinstance(value, str):
        value = datetime.date.fromisoformat(value)
    return f'{value:%d-%m-%Y}'


def deliver(customer, message, kind, user=None, reference=''):
    """Send one SMS to the customer and record the result. Never raises: a gateway problem must never
    stop a payment from being saved. Returns the SmsLog, or None if the customer is excluded.
    `reference` (e.g. the receipt number) is passed to the gateway so the message can be traced there."""
    if not customer.sms_enabled or not customer.phone:
        return None
    backend = get_backend()
    status, error, gateway_id = SmsLog.Status.SENT if backend.delivers else SmsLog.Status.LOGGED, '', ''
    try:
        gateway_id = backend.send(customer.phone, message, reference) or ''
    except SmsError as exc:
        status, error = SmsLog.Status.FAILED, str(exc)[:300]
    except Exception as exc:  # noqa: BLE001 - any gateway fault is recorded, never raised
        status, error = SmsLog.Status.FAILED, f'{type(exc).__name__}: {exc}'[:300]
    return SmsLog.objects.create(
        customer=customer, phone=customer.phone, kind=kind, message=message, status=status, error=error,
        gateway_id=gateway_id[:100], sent_by=user,
    )


def _customer_values(customer):
    return {
        'customer': customer.display_name, 'name': customer.name, 'customer_id': customer.customer_code, 'company': _company(),
    }


def _sale_values(sale):
    return {
        **_customer_values(sale.customer),
        'flat': sale.flat.flat_no, 'building': sale.project.project_name,
        'project': sale.project.development.name if sale.project.development_id else '',
        'sale_no': sale.sale_no, 'sale_value': money(sale.sale_value), 'reg_value': money(sale.reg_value),
        'net_value': money(sale.net_value), 'received': money(sale.received_amount), 'balance_due': money(sale.receivable_amount),
    }


def booking_message(sale):
    return render('BOOKING', {**_sale_values(sale), 'sale_date': _day(sale.sale_date)})


def notify_booking(sale, user=None):
    """SMS when a flat is booked for a customer (skipped for customers excluded from SMS)."""
    return deliver(sale.customer, booking_message(sale), SmsLog.Kind.BOOKING, user, reference=sale.sale_no)


def payment_message(payment):
    sale = payment.sale
    if sale.receivable_amount > 0:
        note = f', balance due {money(sale.receivable_amount)}.'
    elif sale.customer_balance > 0:
        note = f'; your credit balance is {money(sale.customer_balance)}.'
    else:
        note = '; fully paid.'
    return render('PAYMENT', {
        **_sale_values(sale), 'amount': money(payment.amount), 'date': _day(payment.payment_date), 'purpose': payment.purpose_text,
        'receipt_no': payment.receipt_no, 'total_paid': money(sale.received_amount), 'balance_note': note,
    })


def notify_payment(payment, user=None):
    """SMS on every payment received (skipped for customers excluded from SMS)."""
    return deliver(payment.customer, payment_message(payment), SmsLog.Kind.PAYMENT, user, reference=payment.receipt_no)


def customer_statement(customer, development=None):
    """Open bookings of a customer with what is still due on each (only those in `development`, when one is given)."""
    rows = []
    sales = customer.sales.exclude(status='CANCELLED').select_related('flat', 'project')
    if development is not None:
        sales = sales.filter(project__development=development)
    for sale in sales:
        rows.append({
            'sale': sale, 'net': sale.net_value, 'received': sale.received_amount,
            'due': sale.receivable_amount, 'credit': sale.customer_balance,
        })
    return rows


def reminder_message(customer, development=None):
    rows = [row for row in customer_statement(customer, development) if row['due'] > 0]
    if not rows:
        return ''
    details = '; '.join(f'flat {r["sale"].flat.flat_no} ({r["sale"].project.project_name}): {money(r["due"])}' for r in rows)
    total = sum((r['due'] for r in rows), ZERO)
    return render('REMINDER', {**_customer_values(customer), 'total_due': money(total), 'details': details})


def customers_with_dues(development=None):
    """Customers with something still due, for the reminder screen (only what is due in `development`, when given)."""
    from customers.models import Customer

    result = []
    for customer in Customer.objects.prefetch_related('sales').order_by('name'):
        due = sum((
            s.receivable_amount for s in customer.sales.all()
            if s.status != 'CANCELLED' and (development is None or s.project.development_id == development.pk)
        ), ZERO)
        if due > 0:
            customer.total_due = due
            result.append(customer)
    return result


def send_reminders(customers, user, development=None):
    """Send a balance reminder to each customer (excluded customers and customers with nothing due are skipped)."""
    sent, skipped = [], []
    for customer in customers:
        message = reminder_message(customer, development)
        reference = f'REM-{customer.pk}-{datetime.date.today():%Y%m%d}'
        log = deliver(customer, message, SmsLog.Kind.REMINDER, user, reference=reference) if message else None
        (sent if log else skipped).append(customer)
    return sent, skipped


def backend_description():
    backend = get_backend()
    if backend.delivers:
        names = {'zendsms': 'ZendSMS', 'smsnetbd': 'sms.net.bd'}
        return f'{names.get(backend.name, backend.name)} - messages are really sent'
    return 'No gateway configured - messages are only recorded in the log'


def gateway_balance():
    """The SMS balance reported by the gateway, as readable text. Raises SmsError if it cannot be read."""
    data = get_backend().balance()
    if isinstance(data, dict):
        return ', '.join(f'{key.replace("_", " ")}: {value}' for key, value in data.items())
    return str(data)
