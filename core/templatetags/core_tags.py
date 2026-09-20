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
