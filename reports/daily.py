"""The day book: every transaction of a day (or period) in one project, with whether it has been verified.

A transaction is "verified" once a user has confirmed it on the books (see books.ledger): only then does it enter the
book and count towards an account's balance. This report lists both kinds side by side so each day can be checked.
"""
import datetime
from collections import OrderedDict
from decimal import Decimal

from books.ledger import collect_entries, confirmable_model
from core.formatting import DATE, INT, MONEY

from .tables import Column, ReportTable

ZERO = Decimal('0')
VERIFIED, PENDING, NO_ACCOUNT = 'Verified', 'Pending', 'No account yet'


def day_entries(development, date_from, date_to):
    """Every line of the project dated within the period, oldest first. Includes lines that still have no account."""
    entries = collect_entries(development=development) + collect_entries(unassigned=True, development=development)
    entries = [e for e in entries if date_from <= e.date <= date_to]
    entries.sort(key=lambda e: (e.date, e.order, e.key))
    return entries


def verification_details(entries):
    """key -> (who verified it, when) for the verified entries."""
    wanted = {}
    for entry in entries:
        if entry.confirmed:
            kind, pk = entry.key.split(':')
            wanted.setdefault(kind, []).append(int(pk))
    details = {}
    for kind, ids in wanted.items():
        model = confirmable_model(kind)
        for item in model.objects.filter(pk__in=ids).select_related('confirmed_by'):
            user = item.confirmed_by
            details[f'{kind}:{item.pk}'] = ((user.get_full_name() or user.username) if user else '', item.confirmed_at)
    return details


def status_of(entry):
    if entry.confirmed:
        return VERIFIED
    return PENDING if entry.account else NO_ACCOUNT


def period_text(date_from, date_to):
    if date_from == date_to:
        return f'{date_from:%A, %d %b %Y}'
    return f'{date_from:%d %b %Y} to {date_to:%d %b %Y}'


def day_book(development, date_from, date_to):
    """Everything the screen, the PDF, the Excel file and the automatic report need, worked out once."""
    entries = day_entries(development, date_from, date_to)
    details = verification_details(entries)
    for entry in entries:
        entry.status = status_of(entry)
        who, at = details.get(entry.key, ('', None))
        entry.verified_by, entry.verified_at = who, at

    by_source, by_account = OrderedDict(), OrderedDict()
    for entry in entries:
        for table, label in ((by_source, entry.source), (by_account, entry.account.name if entry.account else NO_ACCOUNT)):
            row = table.setdefault(label, {'count': 0, 'in': ZERO, 'out': ZERO, 'verified': 0, 'pending': 0})
            row['count'] += 1
            row['in'] += entry.money_in
            row['out'] += entry.money_out
            row['verified' if entry.status == VERIFIED else 'pending'] += 1
    return {
        'entries': entries,
        'date_from': date_from, 'date_to': date_to,
        'money_in': sum((e.money_in for e in entries), ZERO),
        'money_out': sum((e.money_out for e in entries), ZERO),
        'verified': sum(1 for e in entries if e.status == VERIFIED),
        'pending': sum(1 for e in entries if e.status != VERIFIED),
        'to_verify': [e for e in entries if e.status == PENDING],
        'by_source': by_source, 'by_account': by_account,
    }


def daily_transactions_report(development, date_from, date_to, book=None):
    """(filter lines, tables) of the day book, for the PDF and the Excel file."""
    book = book or day_book(development, date_from, date_to)
    lines = [f'Project: {development.name}', f'Transactions of {period_text(date_from, date_to)}']

    def summary(title, first, data):
        rows = [[name, v['count'], v['in'], v['out'], v['verified'], v['pending']] for name, v in data.items()]
        totals = ['Total', sum(r[1] for r in rows), book['money_in'], book['money_out'], book['verified'], book['pending']] if rows else None
        return ReportTable(
            title, [Column(first), Column('Entries', INT), Column('Money in', MONEY), Column('Money out', MONEY),
                    Column('Verified', INT), Column('Not verified', INT)], rows, totals,
        )

    transactions = ReportTable(
        'Transactions',
        [Column('Date', DATE), Column('Source'), Column('Ref.'), Column('Particulars'), Column('Account'),
         Column('Money in', MONEY), Column('Money out', MONEY), Column('Status'), Column('Verified by')],
        [[e.date, e.source, e.reference, e.description, e.account.name if e.account else '-', e.money_in or None,
          e.money_out or None, e.status,
          f'{e.verified_by} {e.verified_at:%d %b %H:%M}' if e.verified_at else ''] for e in book['entries']],
        ['Total', '', '', '', '', book['money_in'], book['money_out'],
         f'{book["verified"]} verified, {book["pending"]} not', ''] if book['entries'] else None,
        note='Verified = confirmed on the books, so it is in the book and counts towards the account balance. '
             'Not verified entries are still waiting to be checked.',
    )
    return lines, [summary('By kind of transaction', 'Kind', book['by_source']),
                   summary('By account', 'Account', book['by_account']), transactions]


def parse_day(value, default=None):
    try:
        return datetime.date.fromisoformat(value) if value else default
    except ValueError:
        return default
