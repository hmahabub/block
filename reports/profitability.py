"""Profitability analysis of a project: what the company earns, what it spends, what it still stands to earn."""
from collections import OrderedDict
from decimal import Decimal

from core.formatting import INT, MONEY, PERCENT
from costing.models import Phase
from projects.models import Flat
from sales.models import FlatSale

from .builders import _active_sales, _percent, _projects, _sum, project_line
from .tables import Column, ReportTable

ZERO = Decimal('0')


def profitability_report(project=None, development=None):
    """The company's result (base price earned from share sales + money kept on cancellations - pre-development
    cost), per building, what it would be once every flat is sold at base price, and the cash actually in hand."""
    rows, cash_rows = [], []
    cost_by_head = OrderedDict()
    for item in _projects(project, development):
        active = _active_sales(item)
        all_sales = list(item.sales.prefetch_related('honorarium_payments', 'refund_payments'))
        cancelled = [s for s in all_sales if s.status == FlatSale.Status.CANCELLED]
        sale_value = _sum(s.sale_value for s in active)
        honorarium = _sum(s.honorarium for s in active)
        earned = sale_value - honorarium
        retained = _sum(s.retained_on_cancellation for s in cancelled)
        revenue = earned + retained
        pre_cost = item.cost_total(Phase.PRE)
        profit = revenue - pre_cost
        unsold = item.flats.filter(status=Flat.Status.AVAILABLE).count()
        potential = unsold * item.base_price
        name = f'{item.project_code} {item.project_name}'
        rows.append([
            name, len(active), sale_value, honorarium, earned, retained, pre_cost, profit, _percent(profit, revenue),
            _percent(profit, pre_cost), unsold, potential, profit + potential,
        ])

        received = _sum(s.received_amount for s in all_sales)
        refunds_paid = _sum(s.refund_paid for s in all_sales)
        honorarium_paid = _sum(s.honorarium_paid for s in all_sales)
        paid_costs = list(item.costs.prefetch_related('payments'))
        pre_paid = _sum(c.paid_amount for c in paid_costs if c.phase == Phase.PRE)
        post_paid = _sum(c.paid_amount for c in paid_costs if c.phase == Phase.POST)
        cash_rows.append([
            name, received, refunds_paid, honorarium_paid, pre_paid, post_paid,
            received - refunds_paid - honorarium_paid - pre_paid - post_paid,
        ])
        for cost in item.costs.select_related('cost_category', 'cost_category__parent_category'):
            head = (cost.cost_category.parent_category or cost.cost_category).name
            cost_by_head[(head, cost.phase)] = cost_by_head.get((head, cost.phase), ZERO) + cost.amount

    def totals(table_rows, skip=()):
        if not table_rows:
            return None
        return ['Total'] + [None if i in skip else _sum(r[i] for r in table_rows) for i in range(1, len(table_rows[0]))]

    profit_totals = totals(rows, skip=(8, 9))
    if rows:
        revenue_total = profit_totals[4] + profit_totals[5]
        profit_totals[8] = _percent(profit_totals[7], revenue_total)
        profit_totals[9] = _percent(profit_totals[7], profit_totals[6])
    tables = [ReportTable(
        'Profitability by building',
        [Column('Building'), Column('Flats sold', INT), Column('Sale value', MONEY), Column('Honorarium to refs', MONEY),
         Column('Base price earned', MONEY), Column('Kept on cancellations', MONEY), Column('Pre-development cost', MONEY),
         Column('Profit / (loss)', MONEY), Column('Margin on revenue', PERCENT), Column('Return on cost', PERCENT),
         Column('Flats unsold', INT), Column('Unsold at base price', MONEY), Column('Profit if all sold', MONEY)],
        rows, profit_totals,
        note='Profit / (loss) = base price earned (sale value less honorarium) + money kept on cancelled bookings - pre-development '
             "cost. Post-development cost is shared by the flat owners, so it is not the company's cost. 'Profit if all sold' adds "
             'the unsold flats at their base price.',
    )]

    if cost_by_head:
        total_cost = _sum(cost_by_head.values())
        head_rows = [[head, 'Pre-development' if phase == Phase.PRE else 'Post-development', amount, _percent(amount, total_cost)]
                     for (head, phase), amount in sorted(cost_by_head.items(), key=lambda kv: -kv[1])]
        tables.append(ReportTable(
            'Cost by head', [Column('Cost head'), Column('Phase'), Column('Amount', MONEY), Column('Share of cost', PERCENT)],
            head_rows, ['Total', '', total_cost, 100],
        ))

    tables.append(ReportTable(
        'Cash position (money actually moved)',
        [Column('Building'), Column('Received from customers', MONEY), Column('Refunds paid', MONEY),
         Column('Honorarium paid', MONEY), Column('Pre-development cost paid', MONEY), Column('Post-development cost paid', MONEY),
         Column('Net cash', MONEY)],
        cash_rows, totals(cash_rows),
        note='Net cash = received - refunds paid - honorarium paid - cost payments made. Unpaid cost vouchers are not in it.',
    ))
    return [project_line(project, development), 'Position as of today'], tables
