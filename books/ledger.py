"""The single book.

Nothing is typed into the book. Every line is collected from the module where the money was first
recorded, so there is no double entry:

    payments received from customers   (sales.CustomerPayment)      money in
    refunds to customers               (sales.RefundPayment)         money out
    honorarium paid to references      (sales.HonorariumPayment)     money out
    cost payments                      (costing.CostPayment)         money out (older costs paid in full when recorded: costing.ProjectCost)
    director investments               (directors.DirectorTransaction) money in
    director capital/profit withdrawals (directors.DirectorTransaction) money out
    internal transfers                 (books.Transfer)              out of one account, into another

A collected line only enters the book once a user has confirmed it on the "Confirm entries" page. Confirming
cannot be undone, and an account's balance may never go below zero: a confirmation that would do that is refused.
"""
from dataclasses import dataclass
from decimal import Decimal

from django.db import transaction
from django.urls import reverse

from activity_log.services import log_activity

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
    from costing.models import CostPayment, ProjectCost
    from directors.models import DirectorTransaction
    from sales.models import CustomerPayment, HonorariumPayment, RefundPayment

    from .models import Transfer

    return {
        'cp': CustomerPayment, 'rf': RefundPayment, 'hp': HonorariumPayment,
        'pc': ProjectCost, 'cx': CostPayment, 'dt': DirectorTransaction, 'tr': Transfer,
    }


def confirmable_model(kind):
    return _sources().get(kind)


def collect_entries(accounts=None, unassigned=False, confirmed=None, development=None):
    """Book lines for the given accounts (a list), or every account.

    With a `development` only that project's lines are returned (internal transfers belong to no project, so they are
    left out).

    `confirmed=True` gives only what is in the book, `False` only what is waiting for confirmation, `None` both.
    With `unassigned=True` returns instead the lines that have no account yet (older records made before
    accounts existed); they cannot be confirmed until an account is chosen.
    """
    from costing.models import CostPayment, ProjectCost
    from directors.models import DirectorTransaction
    from sales.models import CustomerPayment, HonorariumPayment, RefundPayment

    from .models import Transfer

    def scope(queryset, via, field='account'):
        if development is not None:
            queryset = queryset.filter(**{via: development})
        if unassigned:
            queryset = queryset.filter(**{f'{field}__isnull': True})
        elif accounts is not None:
            queryset = queryset.filter(**{f'{field}__in': accounts})
        else:
            queryset = queryset.filter(**{f'{field}__isnull': False})
        if confirmed is not None:
            queryset = queryset.filter(confirmed_at__isnull=not confirmed)
        return queryset

    entries = []

    for item in scope(CustomerPayment.objects.select_related('account', 'sale', 'customer', 'sale__flat'), 'sale__project__development'):
        entries.append(Entry(
            f'cp:{item.pk}', item.payment_date, 1, 'Payment received', item.receipt_no,
            f'{item.customer.name} - {item.sale.flat.flat_no} ({item.sale.sale_no})',
            item.account, item.amount, ZERO, item.is_confirmed, item.sale.get_absolute_url(),
        ))
    for item in scope(RefundPayment.objects.select_related('account', 'sale', 'sale__customer', 'sale__flat'), 'sale__project__development'):
        entries.append(Entry(
            f'rf:{item.pk}', item.date, 2, 'Refund to customer', item.reference_no,
            f'{item.sale.customer.name} - {item.sale.flat.flat_no} ({item.sale.sale_no})',
            item.account, ZERO, item.amount, item.is_confirmed, item.sale.get_absolute_url(),
        ))
    for item in scope(HonorariumPayment.objects.select_related('account', 'sale', 'sale__ref', 'sale__flat'), 'sale__project__development'):
        who = item.sale.ref.name if item.sale.ref else 'reference'
        entries.append(Entry(
            f'hp:{item.pk}', item.date, 3, 'Honorarium paid', item.reference_no,
            f'{who} - {item.sale.flat.flat_no} ({item.sale.sale_no})',
            item.account, ZERO, item.amount, item.is_confirmed, item.sale.get_absolute_url(),
        ))
    # Older costs that were paid in full when recorded. A cost with no account is an unpaid voucher, not a missing account.
    for item in ([] if unassigned else scope(ProjectCost.objects.select_related('account', 'project', 'cost_category', 'supplier'), 'project__development')):
        who = item.payee or item.description or 'cost'
        entries.append(Entry(
            f'pc:{item.pk}', item.date, 4, 'Cost payment', item.voucher_no,
            f'{item.cost_category} - {who} ({item.project.project_code})',
            item.account, ZERO, item.amount, item.is_confirmed, item.get_absolute_url(),
        ))

    for item in scope(CostPayment.objects.select_related('account', 'cost', 'cost__project', 'cost__cost_category', 'cost__supplier'), 'cost__project__development'):
        cost = item.cost
        entries.append(Entry(
            f'cx:{item.pk}', item.date, 4, 'Cost payment', item.payment_no,
            f'{cost.cost_category} - {cost.payee or cost.description or "cost"} ({cost.project.project_code}) - {cost.voucher_no}',
            item.account, ZERO, item.amount, item.is_confirmed, cost.get_absolute_url(),
        ))

    for item in scope(DirectorTransaction.objects.select_related('account', 'director', 'development'), 'development'):
        investing = item.kind == item.Kind.INVESTMENT
        entries.append(Entry(
            f'dt:{item.pk}', item.date, 3 if not investing else 1, f'Director {item.get_kind_display().lower()}',
            item.reference_no, f'{item.director.name} - {item.development.name}',
            item.account, item.amount if investing else ZERO, ZERO if investing else item.amount,
            item.is_confirmed, item.get_absolute_url(),
        ))

    if not unassigned and development is None:
        transfers = Transfer.objects.select_related('from_account', 'to_account')
        if confirmed is not None:
            transfers = transfers.filter(confirmed_at__isnull=not confirmed)
        ids = None
        if accounts is not None:
            ids = [a.pk if hasattr(a, 'pk') else a for a in accounts]
            transfers = transfers.filter(from_account__in=ids) | transfers.filter(to_account__in=ids)
        for item in transfers.distinct():
            url = reverse('books:transfers')
            text = f'{item.from_account} to {item.to_account}' + (f' - {item.notes}' if item.notes else '')
            if ids is None or item.from_account_id in ids:
                entries.append(Entry(
                    f'tr:{item.pk}', item.date, 5, 'Transfer out', item.reference_no, text,
                    item.from_account, ZERO, item.amount, item.is_confirmed, url,
                ))
            if ids is None or item.to_account_id in ids:
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


def lowest_balance(account):
    """The lowest the account's balance ever gets across its confirmed lines (the opening balance counts)."""
    balance = lowest = account.opening_balance
    for entry in collect_entries([account], confirmed=True):
        balance += entry.money_in - entry.money_out
        lowest = min(lowest, balance)
    return lowest


def account_summaries(accounts, development=None):
    """Per account: opening balance, the balance of what is confirmed, and how many lines still wait.

    With a `development` only that project's lines count and the opening balance is left out (it belongs to the company),
    so `balance` is then the project's net movement through the account."""
    accounts = list(accounts)
    confirmed = {account.pk: [] for account in accounts}
    for entry in collect_entries(accounts, confirmed=True, development=development):
        confirmed[entry.account.pk].append(entry)
    waiting = {account.pk: 0 for account in accounts}
    for entry in collect_entries(accounts, confirmed=False, development=development):
        waiting[entry.account.pk] += 1
    rows = []
    for account in accounts:
        entries = confirmed[account.pk]
        money_in = sum((e.money_in for e in entries), ZERO)
        money_out = sum((e.money_out for e in entries), ZERO)
        opening = ZERO if development is not None else account.opening_balance
        rows.append({
            'account': account,
            'opening': opening,
            'balance': opening + money_in - money_out,
            'money_in': money_in,
            'money_out': money_out,
            'pending_count': waiting[account.pk],
        })
    return rows


def pending_count(development=None):
    """Lines waiting for confirmation, across every account (shown as a badge in the menu)."""
    from costing.models import CostPayment, ProjectCost
    from directors.models import DirectorTransaction
    from sales.models import CustomerPayment, HonorariumPayment, RefundPayment

    from .models import Transfer

    models = {
        CustomerPayment: 'sale__project__development', RefundPayment: 'sale__project__development',
        HonorariumPayment: 'sale__project__development', ProjectCost: 'project__development',
        CostPayment: 'cost__project__development', DirectorTransaction: 'development',
    }
    total = 0
    for model, via in models.items():
        waiting = model.objects.filter(confirmed_at__isnull=True, account__isnull=False)
        total += (waiting.filter(**{via: development}) if development is not None else waiting).count()
    if development is not None:
        return total
    return total + Transfer.objects.filter(confirmed_at__isnull=True).count()


def unassigned_count(development=None):
    """Records with no account yet (made before accounts existed)."""
    return len(collect_entries(unassigned=True, development=development))


@transaction.atomic
def confirm_entries(keys, user):
    """Confirm the lines named by `keys` (e.g. 'cp:12'), oldest first.

    A line that would take any account below zero is left unconfirmed. Returns (confirmed keys, problems),
    where problems is a list of readable reasons. Confirming cannot be undone.
    """
    wanted = set(keys)
    waiting = collect_entries(confirmed=False)
    done, problems, seen = [], [], set()
    models = _sources()

    for entry in waiting:
        if entry.key not in wanted or entry.key in seen:
            continue
        seen.add(entry.key)
        kind, _, pk = entry.key.partition(':')
        item = models[kind].objects.get(pk=pk)
        item.confirm(user)
        broken = _accounts_gone_negative(item, kind)
        if broken:
            # Take the confirmation straight back: it was never in the book, so nothing is recorded.
            type(item).objects.filter(pk=item.pk).update(confirmed_at=None, confirmed_by=None)
            problems.append(f'{entry.reference} ({entry.source}, {entry.date:%d %b %Y}) would take {broken} below zero.')
        else:
            done.append(entry.key)
            # .update() sends no signals, so the confirmation is written to the audit trail here.
            log_activity(user, 'updated', item, changes={'confirmed_at': [None, item.confirmed_at.replace(microsecond=0).isoformat()],
                                                         'confirmed_by': [None, getattr(user, 'pk', None)]})

    for key in wanted - seen:
        problems.append(f'{key} could not be confirmed (already confirmed, unknown, or it has no account).')
    return done, problems


def _accounts_gone_negative(item, kind):
    accounts = [item.from_account, item.to_account] if kind == 'tr' else [item.account]
    for account in accounts:
        if lowest_balance(account) < 0:
            return account.name
    return ''


@transaction.atomic
def assign_account(keys, account):
    """Give an account to older customer payments that were recorded before accounts existed.

    Only unconfirmed lines that have no account yet are touched. Returns how many were updated.
    """
    models = _sources()
    updated = 0
    for key in set(keys):
        kind, _, pk = key.partition(':')
        model = models.get(kind)
        if model is None or kind != 'cp' or not pk.isdigit():
            continue
        changes = {'account': account}
        if kind == 'cp':  # the payment method follows the account (an update() skips the model's save())
            changes['payment_method'] = 'CASH' if account.is_cash else 'BANK'
        found = model.objects.filter(pk=pk, account__isnull=True, confirmed_at__isnull=True).first()
        count = model.objects.filter(pk=pk, account__isnull=True, confirmed_at__isnull=True).update(**changes)
        if count and found is not None:
            log_activity(None, 'updated', found, changes={'account': [None, account.pk]})
        updated += count
    return updated
