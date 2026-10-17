"""Sending an invoice to a customer on WhatsApp.

WhatsApp's business API needs an approved Meta account and message templates, so this uses WhatsApp's own
"click to chat" link instead: pressing Send opens WhatsApp (app or web) with the customer's number and the
message already typed, and the user presses send there. Nothing leaves the system until they do.

A WhatsApp message cannot carry a file from a link, so the message holds a private link to the invoice page.
The link is signed (nobody can guess or alter it) and stops working after LINK_DAYS days.
"""
from decimal import Decimal
from urllib.parse import quote

from django.conf import settings
from django.core import signing
from django.urls import reverse

LINK_DAYS = 30
SALT = 'sale-invoice-link'


def whatsapp_digits(number):
    """The number as wa.me wants it: country code and digits only (+8801711000000 -> 8801711000000)."""
    return ''.join(ch for ch in (number or '') if ch.isdigit())


def has_whatsapp(customer):
    return 10 <= len(whatsapp_digits(customer.whatsapp_no)) <= 15


def invoice_token(sale):
    return signing.dumps(sale.pk, salt=SALT)


def sale_pk_from_token(token):
    """The sale id inside a valid, unexpired invoice link token, else None."""
    try:
        return signing.loads(token, salt=SALT, max_age=LINK_DAYS * 86400)
    except signing.BadSignature:  # includes SignatureExpired
        return None


def invoice_url(request, sale):
    """The full address of the customer's invoice page.

    SITE_URL (e.g. https://erp.example.com) is used when set, so links are right even when a hosting proxy hides
    that the site is on https; otherwise the address the user is browsing from."""
    path = reverse('sales:invoice-shared', args=[invoice_token(sale)])
    if settings.SITE_URL:
        return settings.SITE_URL.rstrip('/') + path
    return request.build_absolute_uri(path)


def _amount(value):
    return f'Tk {Decimal(value):,.2f}'


def invoice_message(sale, url):
    from core.models import CompanyProfile

    text = (
        f'Dear {sale.customer.display_name}, here is your invoice {sale.sale_no} for flat {sale.flat.flat_no}, '
        f'{sale.project.project_name}. Net value {_amount(sale.net_value)}, received {_amount(sale.received_amount)}'
    )
    if sale.receivable_amount > 0:
        text += f', balance due {_amount(sale.receivable_amount)}'
    text += f'. View or print it here (link valid {LINK_DAYS} days): {url} - {CompanyProfile.current().display_name}'
    return text


def whatsapp_link(number, text):
    return f'https://wa.me/{whatsapp_digits(number)}?text={quote(text)}'
