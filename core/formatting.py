"""Cell formatting shared by the on-screen reports and their PDFs, so both always read the same."""
import datetime
from decimal import Decimal

TEXT, MONEY, INT, PERCENT, DATE = 'text', 'money', 'int', 'percent', 'date'
NUMERIC_KINDS = (MONEY, INT, PERCENT)


def format_cell(value, kind=TEXT):
    if value is None or value == '':
        return '-'
    if kind == MONEY:
        return f'{Decimal(value):,.2f}'
    if kind == INT:
        return f'{int(value):,}'
    if kind == PERCENT:
        return f'{Decimal(value):.1f}%'
    if kind == DATE and isinstance(value, (datetime.date, datetime.datetime)):
        return f'{value:%d %b %Y}'
    return str(value)
