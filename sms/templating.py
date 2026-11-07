"""SMS wording lives in .env (SMS_TEMPLATE_PAYMENT, SMS_TEMPLATE_BOOKING, SMS_TEMPLATE_REMINDER, SMS_TEMPLATE_INSTALLMENT), so it can be changed
without touching the code. A template is plain text with {placeholders}; each message type has its own set.

Only {name}-style placeholders are substituted. Anything else is left exactly as written (an unknown {typo} shows up
as-is in the SMS log, so a mistake is easy to spot), and nothing in a template can reach into the program.
"""
import re
from decimal import Decimal

from django.conf import settings

_PLACEHOLDER = re.compile(r'\{(\w+)\}')

# What each message can say. The first block is shared by every message.
COMMON = {
    'customer': 'the customer with title, e.g. Mr. Rahim Uddin',
    'name': 'the customer name without a title',
    'customer_id': 'the customer ID, e.g. C0001',
    'company': 'the company name',
}
SALE = {
    'flat': 'the flat number, e.g. A1',
    'building': 'the building name',
    'project': 'the project name (blank if the building has none)',
    'sale_no': 'the sale number',
    'sale_value': 'what the customer agreed to pay for the flat, e.g. Tk 15,300,000.00',
    'reg_value': 'the registration cost',
    'net_value': 'sale value plus registration cost',
    'received': 'everything the customer has paid so far',
    'balance_due': 'what the customer still owes (Tk 0.00 when paid)',
}
PLACEHOLDERS = {
    'PAYMENT': {**COMMON, **SALE, 'amount': 'the amount just received', 'date': 'the payment date, dd-mm-yyyy',
                'receipt_no': 'the money receipt number',
                'purpose': 'what the payment was for: Flat booking, or the installment it paid',
                'total_paid': 'same as {received}',
                'balance_note': 'a ready sentence: ", balance due Tk X." or "; fully paid." or "; your credit balance is Tk X."'},
    'BOOKING': {**COMMON, **SALE, 'sale_date': 'the booking date, dd-mm-yyyy'},
    'REMINDER': {**COMMON, 'total_due': 'everything the customer owes across all flats',
                 'details': 'each flat with what is due on it, e.g. "flat A1 (Tower 1): Tk 1,200.00"'},
    'INSTALLMENT': {**COMMON, **SALE, 'installment': 'the installment title, e.g. Installment 3',
                    'amount': 'the amount added as due, e.g. Tk 500,000.00',
                    'deadline': 'the payment deadline, dd-mm-yyyy',
                    'installment_due': 'everything now due on this flat in installments, including this one'},
}
SETTING_NAMES = {
    'PAYMENT': 'SMS_TEMPLATE_PAYMENT', 'BOOKING': 'SMS_TEMPLATE_BOOKING', 'REMINDER': 'SMS_TEMPLATE_REMINDER',
    'INSTALLMENT': 'SMS_TEMPLATE_INSTALLMENT',
}


def money(value):
    return f'Tk {Decimal(value):,.2f}'


def render(kind, values):
    """Fill the template for `kind` ('PAYMENT', 'BOOKING', 'REMINDER' or 'INSTALLMENT') with `values`."""
    template = getattr(settings, SETTING_NAMES[kind])
    return _PLACEHOLDER.sub(lambda match: str(values.get(match.group(1), match.group(0))), template).strip()


def unknown_placeholders(kind, template=None):
    """Placeholders in the template that this message type does not offer (typos), for checking a template."""
    template = getattr(settings, SETTING_NAMES[kind]) if template is None else template
    return sorted({name for name in _PLACEHOLDER.findall(template) if name not in PLACEHOLDERS[kind]})
