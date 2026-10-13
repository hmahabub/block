"""The single book.

Nothing is typed into the book. Every line is collected from the module where the money was first
recorded, so there is no double entry:

    payments received from customers   (sales.CustomerPayment)      money in
    refunds to customers               (sales.RefundPayment)         money out
    honorarium paid to references      (sales.HonorariumPayment)     money out
    cost payments                      (costing.ProjectCost)         money out
    internal transfers                 (books.Transfer)              out of one account, into another

Each line can then be confirmed by a user, which is the extra layer that says "I checked this one".
"""
from dataclasses import dataclass
from decimal import Decimal

from django.urls import reverse

ZERO = Decimal('0')


@dataclass
class Entry:
    key: str
    date: object
    order: int
    source: str
    reference: str
    description: str
    account: object
    money_in: Decimal
    money_out: Decimal
    confirmed: bool
    url: str
    balance: Decimal = None


def _sources():
    """Kind code -> model, loaded lazily so the apps can import each other."""
    from costing.models import ProjectCost
    from sales.models import CustomerPayment, HonorariumPayment, RefundPayment

    from .models import Transfer

    return {
        'cp': CustomerPayment, 'rf': RefundPayment, 'hp': HonorariumPayment,
        'pc': ProjectCost, 'tr': Transfer,
    }


def confirmable_model(kind):
    return _sources().get(kind)


def collect_entries(accounts=None, unassigned=False):
    """All book lines for the given accounts (a queryset/list), or for every account.

    With `unassigned=True` returns instead the lines that have no account yet (older records made
    before accounts existed); they cannot be in any balance until an account is chosen.
    """
    from costing.models import ProjectCost
    from sales.models import CustomerPayment, HonorariumPayment, RefundPayment

    from .models import Transfer

    def scope(queryset, field='account'):
        if unassigned:
            return queryset.filter(**{f'{field}__isnull': True})
        if accounts is not None:
            return queryset.filter(**{f'{field}__in': accounts})
        return queryset.filter(**{f'{field}__isnull': False})

    entries = []

    for item in scope(CustomerPayment.objects.select_related('account', 'sale', 'customer', 'sale__flat')):
        entries.append(Entry(
            f'cp:{item.pk}', item.payment_date, 1, 'Payment received', item.receipt_no,
            f'{item.customer.name} - {item.sale.flat.flat_no} ({item.sale.sale_no})',
            item.account, item.amount, ZERO, item.is_confirmed, item.sale.get_absolute_url(),
        ))
    for item in scope(RefundPayment.objects.select_related('account', 'sale', 'sale__customer', 'sale__flat')):
        entries.append(Entry(
            f'rf:{item.pk}', item.date, 2, 'Refund to customer', item.reference_no,
            f'{item.sale.customer.name} - {item.sale.flat.flat_no} ({item.sale.sale_no})',
            item.account, ZERO, item.amount, item.is_confirmed, item.sale.get_absolute_url(),
        ))
    for item in scope(HonorariumPayment.objects.select_related('account', 'sale', 'sale__ref', 'sale__flat')):
        who = item.sale.ref.name if item.sale.ref else 'reference'
        entries.append(Entry(
            f'hp:{item.pk}', item.date, 3, 'Honorarium paid', item.reference_no,
            f'{who} - {item.sale.flat.flat_no} ({item.sale.sale_no})',
            item.account, ZERO, item.amount, item.is_confirmed, item.sale.get_absolute_url(),
        ))
    for item in scope(ProjectCost.objects.select_related('account', 'project', 'cost_category', 'supplier')):
        who = item.supplier.name if item.supplier else (item.description or 'cost')
        entries.append(Entry(
            f'pc:{item.pk}', item.date, 4, 'Cost payment', item.voucher_no,
            f'{item.cost_category} - {who} ({item.project.project_code})',
            item.account, ZERO, item.amount, item.is_confirmed, item.get_absolute_url(),
        ))

    if not unassigned:
        transfers = Transfer.objects.select_related('from_account', 'to_account')
        if accounts is not None:
            ids = [a.pk if hasattr(a, 'pk') else a for a in accounts]
            transfers = transfers.filter(from_account__in=ids) | transfers.filter(to_account__in=ids)
        for item in transfers.distinct():
            url = reverse('books:transfers')
            text = f'{item.from_account} to {item.to_account}' + (f' - {item.notes}' if item.notes else '')
            if accounts is None or item.from_account in accounts:
                entries.append(Entry(
                    f'tr:{item.pk}', item.date, 5, 'Transfer out', item.reference_no, text,
                    item.from_account, ZERO, item.amount, item.is_confirmed, url,
                ))
            if accounts is None or item.to_account in accounts:
                entries.append(Entry(
                    f'tr:{item.pk}', item.date, 6, 'Transfer in', item.reference_no, text,
                    item.to_account, item.amount, ZERO, item.is_confirmed, url,
                ))

    entries.sort(key=lambda e: (e.date, e.order, e.reference))
    return entries


def with_running_balance(entries, opening):
    """Fill in `balance` on each entry, starting from `opening`; returns the closing balance."""
    balance = opening
    for entry in entries:
        balance += entry.money_in - entry.money_out
        entry.balance = balance
    return balance


def account_summaries(accounts):
    """Per account: opening balance, confirmed balance, book balance (everything) and unconfirmed count."""
    accounts = list(accounts)
    by_account = {account.pk: [] for account in accounts}
    for entry in collect_entries(accounts):
        by_account[entry.account.pk].append(entry)
    rows = []
    for account in accounts:
        entries = by_account[account.pk]
        net = sum((e.money_in - e.money_out for e in entries), ZERO)
        confirmed = sum((e.money_in - e.money_out for e in entries if e.confirmed), ZERO)
        rows.append({
            'account': account,
            'opening': account.opening_balance,
            'confirmed_balance': account.opening_balance + confirmed,
            'book_balance': account.opening_balance + net,
            'unconfirmed_count': sum(1 for e in entries if not e.confirmed),
            'money_in': sum((e.money_in for e in entries), ZERO),
            'money_out': sum((e.money_out for e in entries), ZERO),
        })
    return rows


def unassigned_count():
    """Records with no account yet (made before accounts existed)."""
    return len(collect_entries(unassigned=True))
