"""The report definitions. Each builder returns (filter description lines, list of ReportTable)."""
from collections import OrderedDict
from decimal import Decimal

from books.ledger import account_summaries
from books.models import Account
from core.formatting import INT, MONEY, PERCENT
from costing.models import Phase
from projects.models import Flat, Project
from sales.models import CustomerPayment, FlatSale

from .tables import Column, ReportTable

ZERO = Decimal('0')


def _sum(values):
    return sum(values, ZERO)


def _projects(project):
    return [project] if project else list(Project.objects.all())


def _active_sales(project):
    return list(
        project.sales.exclude(status=FlatSale.Status.CANCELLED)
        .select_related('flat', 'customer', 'ref').prefetch_related('honorarium_payments')
    )


def _percent(part, whole):
    return (part / whole * 100) if whole else None


def project_line(project):
    return f'Project: {project.project_name}' if project else 'Project: all'


def period_line(date_from, date_to):
    if date_from and date_to:
        return f'Period: {date_from:%d %b %Y} to {date_to:%d %b %Y}'
    if date_from:
        return f'Period: from {date_from:%d %b %Y}'
    if date_to:
        return f'Period: up to {date_to:%d %b %Y}'
    return 'Period: all dates'


# --- Finance report: every phase together --------------------------------------
def finance_report(project=None):
    sales_rows, cost_rows = [], []
    for item in _projects(project):
        active = _active_sales(item)
        all_sales = list(item.sales.prefetch_related('refund_payments'))
        sale_value = _sum(s.sale_value for s in active)
        honorarium = _sum(s.honorarium for s in active)
        reg = _sum(s.reg_value for s in active)
        net = _sum(s.net_value for s in active)
        received = _sum(s.received_amount for s in all_sales)
        receivable = _sum(s.receivable_amount for s in active)
        sales_rows.append([
            f'{item.project_code} {item.project_name}', item.flat_count, len(active),
            sale_value, honorarium, reg, net, received, receivable,
        ])

        hon_due = _sum(s.honorarium_due for s in active)
        refund_due = _sum(s.refund_due for s in all_sales)
        pre, post = item.cost_total(Phase.PRE), item.cost_total(Phase.POST)
        cost_rows.append([
            f'{item.project_code} {item.project_name}', pre, post, pre + post, hon_due, refund_due, hon_due + refund_due,
        ])

    def totals(rows, first=1):
        return ['Total'] + [_sum(r[i] for r in rows) for i in range(first, len(rows[0]))] if rows else None

    sales_table = ReportTable(
        'Sales, collection and receivable',
        [Column('Project'), Column('Flats', INT), Column('Flats sold', INT), Column('Sale value', MONEY),
         Column('Honorarium', MONEY), Column('Reg value', MONEY), Column('Net value', MONEY),
         Column('Received', MONEY), Column('Receivable', MONEY)],
        sales_rows, totals(sales_rows),
        note='Received includes money from cancelled bookings; receivable counts active bookings only.',
    )
    cost_table = ReportTable(
        'Cost and payable',
        [Column('Project'), Column('Pre-development cost', MONEY), Column('Post-development cost', MONEY),
         Column('Total cost', MONEY), Column('Honorarium payable', MONEY), Column('Refunds payable', MONEY),
         Column('Total payable', MONEY)],
        cost_rows, totals(cost_rows),
        note='Cost entries are paid when recorded, so the only amounts payable are honorarium to references and refunds to customers.',
    )
    tables = [sales_table, cost_table]

    summaries = account_summaries(Account.objects.filter(is_active=True))
    if summaries:
        account_rows = [[r['account'].name, r['account'].get_account_type_display(), r['money_in'], r['money_out'],
                         r['balance'], r['pending_count']] for r in summaries]
        tables.append(ReportTable(
            'Money in hand (accounts)',
            [Column('Account'), Column('Type'), Column('Money in', MONEY), Column('Money out', MONEY),
             Column('Balance', MONEY), Column('Waiting for confirmation', INT)],
            account_rows,
            ['Total', '', _sum(r[2] for r in account_rows), _sum(r[3] for r in account_rows),
             _sum(r[4] for r in account_rows), sum(r[5] for r in account_rows)],
            note='Only confirmed entries are in the book, so only they count towards the balance.',
        ))
    return [project_line(project), 'Position as of today'], tables


# --- Pre-development ------------------------------------------------------------
def periodic_collection_report(project=None, date_from=None, date_to=None):
    payments = CustomerPayment.objects.select_related('sale', 'sale__flat', 'sale__project', 'customer', 'account')
    if project:
        payments = payments.filter(sale__project=project)
    if date_from:
        payments = payments.filter(payment_date__gte=date_from)
    if date_to:
        payments = payments.filter(payment_date__lte=date_to)
    payments = list(payments.order_by('payment_date', 'id'))

    months = OrderedDict()
    for payment in payments:
        key = payment.payment_date.replace(day=1)
        count, amount = months.get(key, (0, ZERO))
        months[key] = (count + 1, amount + payment.amount)
    month_rows, running = [], ZERO
    for key, (count, amount) in months.items():
        running += amount
        month_rows.append([f'{key:%B %Y}', count, amount, running])

    by_sale = OrderedDict()
    for payment in payments:
        row = by_sale.setdefault(payment.sale_id, {'sale': payment.sale, 'amount': ZERO, 'count': 0})
        row['amount'] += payment.amount
        row['count'] += 1
    customer_rows = [
        [r['sale'].customer.name, r['sale'].flat.flat_no, r['count'], r['amount'],
         r['sale'].received_amount, r['sale'].receivable_amount]
        for r in sorted(by_sale.values(), key=lambda r: r['sale'].customer.name.lower())
    ]

    by_account = OrderedDict()
    for payment in payments:
        name = payment.account.name if payment.account else 'No account'
        count, amount = by_account.get(name, (0, ZERO))
        by_account[name] = (count + 1, amount + payment.amount)
    account_rows = [[name, count, amount] for name, (count, amount) in by_account.items()]

    total = _sum(p.amount for p in payments)
    tables = [
        ReportTable('Collection by month', [Column('Month'), Column('Payments', INT), Column('Collected', MONEY), Column('Cumulative', MONEY)],
                    month_rows, ['Total', len(payments), total, None]),
        ReportTable('Collection by customer',
                    [Column('Customer'), Column('Flat'), Column('Payments', INT), Column('Collected in period', MONEY),
                     Column('Received to date', MONEY), Column('Receivable now', MONEY)],
                    customer_rows, ['Total', '', len(payments), total, None, None]),
        ReportTable('Collection by account', [Column('Account'), Column('Payments', INT), Column('Collected', MONEY)],
                    account_rows, ['Total', len(payments), total]),
    ]
    return [project_line(project), period_line(date_from, date_to)], tables


def profit_loss_report(project=None):
    """Pre-development result: what the company earns from selling flat shares at base price,
    against land, marketing and pre-development administrative cost; plus collection and dues."""
    rows = []
    cost_by_category = OrderedDict()
    for item in _projects(project):
        active = _active_sales(item)
        cancelled = list(item.sales.filter(status=FlatSale.Status.CANCELLED))
        base_value = _sum(s.total_base_price for s in active)
        retained = _sum(s.retained_on_cancellation for s in cancelled)
        pre_cost = item.cost_total(Phase.PRE)
        result = base_value + retained - pre_cost
        net = _sum(s.net_value for s in active)
        received = _sum(s.received_amount for s in active)
        due = _sum(s.receivable_amount for s in active)
        honorarium = _sum(s.honorarium for s in active)
        rows.append([
            f'{item.project_code} {item.project_name}', len(active), base_value, retained, pre_cost, result,
            net, received, _percent(received, net), due, honorarium, _sum(s.honorarium_paid for s in active),
        ])
        for cost in item.costs.filter(phase=Phase.PRE).select_related('cost_category', 'cost_category__parent_category'):
            top = cost.cost_category.parent_category or cost.cost_category
            cost_by_category[top.name] = cost_by_category.get(top.name, ZERO) + cost.amount

    totals = None
    if rows:
        net_total, received_total = _sum(r[6] for r in rows), _sum(r[7] for r in rows)
        totals = ['Total', _sum(r[1] for r in rows), _sum(r[2] for r in rows), _sum(r[3] for r in rows),
                  _sum(r[4] for r in rows), _sum(r[5] for r in rows), net_total, received_total,
                  _percent(received_total, net_total), _sum(r[9] for r in rows), _sum(r[10] for r in rows),
                  _sum(r[11] for r in rows)]
    tables = [ReportTable(
        'Pre-development profit / loss, collection and due',
        [Column('Project'), Column('Shares sold', INT), Column('Base price earned', MONEY),
         Column('Kept on cancellations', MONEY), Column('Pre-dev cost', MONEY), Column('Profit / (loss)', MONEY),
         Column('Net value', MONEY), Column('Collected', MONEY), Column('Collected %', PERCENT),
         Column('Due', MONEY), Column('Honorarium', MONEY), Column('Honorarium paid', MONEY)],
        rows, totals,
        note='Profit / (loss) = base price earned from share sales (sale value less honorarium) + money kept on cancelled bookings '
             '- land, marketing and pre-development administrative cost.',
    )]
    if cost_by_category:
        category_rows = sorted(cost_by_category.items(), key=lambda item: -item[1])
        tables.append(ReportTable(
            'Pre-development cost by head', [Column('Cost head'), Column('Amount', MONEY)],
            [[name, amount] for name, amount in category_rows],
            ['Total', _sum(a for _, a in category_rows)],
        ))
    return [project_line(project), 'Pre-development phase'], tables


# --- Post-development -----------------------------------------------------------
def customer_post_report(project=None):
    """Per customer: balance held, receivable, post-development cost share and payable."""
    rows = []
    unsold_flats = 0
    unsold_share = ZERO
    for item in _projects(project):
        for sale in _active_sales(item):
            share = sale.flat.total_cost
            rows.append([
                sale.customer.display_name, sale.flat.flat_no, item.project_code, sale.net_value, sale.received_amount,
                sale.receivable_amount, sale.customer_balance, share, sale.customer_balance - share,
            ])
        for flat in item.flats.all():
            if flat.current_sale is None:
                unsold_flats += 1
                unsold_share += flat.total_cost
    rows.sort(key=lambda r: (r[0].lower(), r[1]))

    cancelled_qs = FlatSale.objects.filter(status=FlatSale.Status.CANCELLED)
    if project:
        cancelled_qs = cancelled_qs.filter(project=project)
    refund_due = _sum(s.refund_due for s in cancelled_qs)

    totals = None
    if rows:
        totals = ['Total', '', ''] + [_sum(r[i] for r in rows) for i in range(3, 9)]
    tables = [ReportTable(
        'Customer balance, cost, receivable and payable',
        [Column('Customer'), Column('Flat'), Column('Project'), Column('Net value', MONEY), Column('Received', MONEY),
         Column('Receivable', MONEY), Column('Customer balance', MONEY), Column('Post-dev cost share', MONEY),
         Column('Balance after cost', MONEY)],
        rows, totals,
        note='Post-development cost is shared equally by every flat, plus any cost recorded against that one flat. '
             'Customer balance is money paid beyond the net value (held for the customer). '
             'Balance after cost = customer balance - cost share: positive is credit, negative is still to be collected.',
    )]
    summary = [
        ['Flats not sold (cost borne by the company)', unsold_flats, unsold_share],
        ['Refunds still payable to customers (cancelled bookings)', None, refund_due],
    ]
    tables.append(ReportTable('Other post-development items', [Column('Item'), Column('Flats', INT), Column('Amount', MONEY)], summary))
    return [project_line(project), 'Post-development phase'], tables


def flat_wise_report(project=None):
    flats = Flat.objects.select_related('project')
    if project:
        flats = flats.filter(project=project)
    rows = []
    for flat in flats:
        sale = flat.current_sale
        rows.append([
            flat.flat_no, flat.project.project_code, flat.get_status_display(),
            sale.customer.name if sale else None, sale.sale_value if sale else None,
            sale.honorarium if sale else None, sale.net_value if sale else None,
            sale.received_amount if sale else None, sale.receivable_amount if sale else None,
            flat.shared_cost_share, flat.direct_cost, flat.total_cost,
        ])
    totals = None
    if rows:
        def col(i):
            return _sum((r[i] or ZERO) for r in rows)
        totals = ['Total', '', '', '', col(4), col(5), col(6), col(7), col(8), col(9), col(10), col(11)]
    table = ReportTable(
        'Flat-wise report',
        [Column('Flat'), Column('Project'), Column('Status'), Column('Customer'), Column('Sale value', MONEY),
         Column('Honorarium', MONEY), Column('Net value', MONEY), Column('Received', MONEY), Column('Receivable', MONEY),
         Column('Shared cost share', MONEY), Column('Direct cost', MONEY), Column('Total cost', MONEY)],
        rows, totals,
    )
    return [project_line(project)], [table]


def dues_report(project=None):
    sales = FlatSale.objects.exclude(status=FlatSale.Status.CANCELLED).filter(receivable_amount__gt=0)
    if project:
        sales = sales.filter(project=project)
    rows = [
        [s.customer.name, s.customer.phone, s.flat.flat_no, s.net_value, s.received_amount, s.receivable_amount]
        for s in sales.select_related('customer', 'flat').order_by('customer__name')
    ]
    totals = ['Total', '', '', _sum(r[3] for r in rows), _sum(r[4] for r in rows), _sum(r[5] for r in rows)] if rows else None
    table = ReportTable(
        'Receivables',
        [Column('Customer'), Column('Phone'), Column('Flat'), Column('Net value', MONEY), Column('Received', MONEY),
         Column('Receivable', MONEY)],
        rows, totals,
    )
    return [project_line(project)], [table]
