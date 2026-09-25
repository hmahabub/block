from decimal import Decimal, InvalidOperation

from django import template
from django.conf import settings
from django.contrib.humanize.templatetags.humanize import intcomma

register = template.Library()


@register.filter(name='taka')
def taka(value, decimals=2):
    """Render a numeric value as a Taka amount, e.g. ৳1,60,00,000.00 -> ৳16,000,000.00.

    Uses plain international thousands grouping (via intcomma), not the
    lakh/crore grouping shown in the planning document's prose examples.
    """
    if value in (None, ''):
        return ''
    try:
        amount = Decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        return value
    formatted = intcomma(f"{amount:.{decimals}f}")
    return f"{settings.CURRENCY_SYMBOL}{formatted}"


@register.filter(name='subtract')
def subtract(value, arg):
    try:
        return Decimal(value) - Decimal(arg)
    except (InvalidOperation, TypeError, ValueError):
        return value


@register.simple_tag(takes_context=True)
def querystring(context, **kwargs):
    """Build a querystring from the current request's GET params with overrides.

    Usage: <a href="?{% querystring page=3 %}">3</a> — keeps q=, status= etc.
    intact while only replacing `page`. Backport of Django 5.1's {% querystring %}
    tag, which isn't available on Django 4.2.
    """
    request = context['request']
    params = request.GET.copy()
    for key, value in kwargs.items():
        if value in (None, ''):
            params.pop(key, None)
        else:
            params[key] = value
    return params.urlencode()


_ONES = ['', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine', 'Ten', 'Eleven',
         'Twelve', 'Thirteen', 'Fourteen', 'Fifteen', 'Sixteen', 'Seventeen', 'Eighteen', 'Nineteen']
_TENS = ['', '', 'Twenty', 'Thirty', 'Forty', 'Fifty', 'Sixty', 'Seventy', 'Eighty', 'Ninety']


def _words_below_100(n):
    if n < 20:
        return _ONES[n]
    return (_TENS[n // 10] + ' ' + _ONES[n % 10]).strip()


def _words_below_1000(n):
    parts = []
    if n >= 100:
        parts.append(_ONES[n // 100] + ' Hundred')
    if n % 100:
        parts.append(_words_below_100(n % 100))
    return ' '.join(parts)


def int_to_words(n):
    """South Asian grouping: crore, lakh, thousand, hundred (e.g. 16000000 -> One Crore Sixty Lakh)."""
    if n == 0:
        return 'Zero'
    parts = []
    crore, rest = divmod(n, 10_000_000)
    if crore:
        parts.append(int_to_words(crore) + ' Crore')
    lakh, rest = divmod(rest, 100_000)
    if lakh:
        parts.append(_words_below_100(lakh) + ' Lakh')
    thousand, rest = divmod(rest, 1000)
    if thousand:
        parts.append(_words_below_100(thousand) + ' Thousand')
    if rest:
        parts.append(_words_below_1000(rest))
    return ' '.join(parts)


@register.filter(name='taka_words')
def taka_words(value):
    """Amount in words for printed documents, e.g. Taka One Crore Sixty Lakh Only."""
    if value in (None, ''):
        return ''
    try:
        amount = Decimal(value).quantize(Decimal('0.01'))
    except (InvalidOperation, TypeError, ValueError):
        return value
    taka, paisa = divmod(int(amount * 100), 100)
    words = f'Taka {int_to_words(taka)}'
    if paisa:
        words += f' and {int_to_words(paisa)} Paisa'
    return words + ' Only'
