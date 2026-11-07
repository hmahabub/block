"""The daily cost report: what was spent, kept apart as pre-development and post-development cost."""
import datetime
from collections import OrderedDict
from decimal import Decimal

from core.formatting import DATE, INT, MONEY, PERCENT
from costing.models import Phase, ProjectCost

from .builders import _percent, _projects, _sum, period_line, project_line
from .tables import Column, ReportTable

ZERO = Decimal('0')
PHASE_NAMES = {Phase.PRE: 'Pre-development', Phase.POST: 'Post-development'}


def _head(cost):
    category = cost.cost_category
    return (category.parent_category or category).name


def _charged_to(cost):
    if cost.flat_id:
        return f'Flat {cost.flat.flat_no}'
    return 'Company' if cost.phase == Phase.PRE else 'All flat owners'


def day_costs(project=None, development=None, date_from=None, date_to=None):
    """The costs of the buildings the report covers within the period, oldest first."""
    costs = ProjectCost.objects.filter(project__in=_projects(project, development))
    if date_from:
        costs = costs.filter(date__gte=date_from)
    if date_to:
        costs = costs.filter(date__lte=date_to)
    return list(costs.select_related(
        'project', 'cost_category', 'cost_category__parent_category', 'supplier', 'flat', 'account',
    ).prefetch_related('payments').order_by('date', 'id'))


def daily_cost_report(project=None, development=None, date_from=None, date_to=None):
    """(filter lines, tables): the totals of each phase, each day of the period, every cost, and the cost heads."""
    costs = day_costs(project, development, date_from, date_to)
    by_phase = {phase: [c for c in costs if c.phase == phase] for phase in (Phase.PRE, Phase.POST)}
    pre, post = _sum(c.amount for c in by_phase[Phase.PRE]), _sum(c.amount for c in by_phase[Phase.POST])

    tables = [ReportTable(
        'Totals',
        [Column('Phase'), Column('Costs', INT), Column('Amount', MONEY), Column('Paid', MONEY), Column('Due', MONEY), Column('Share', PERCENT)],
        [[PHASE_NAMES[phase], len(by_phase[phase]), total, _sum(c.paid_amount for c in by_phase[phase]),
          _sum(c.due_amount for c in by_phase[phase]), _percent(total, pre + post)]
         for phase, total in ((Phase.PRE, pre), (Phase.POST, post))],
        ['Total', len(costs), pre + post, _sum(c.paid_amount for c in costs), _sum(c.due_amount for c in costs), 100 if costs else None],
        note='Pre-development cost is the company\'s and is set against the profit on share sales; post-development cost is '
             'shared equally by the owners of the flats.',
    )]

    days = OrderedDict()
    for cost in costs:
        row = days.setdefault(cost.date, [ZERO, ZERO])
        row[0 if cost.phase == Phase.PRE else 1] += cost.amount
    if len(days) > 1 or (date_from and date_to and date_from != date_to):
        running, day_rows = ZERO, []
        for day, (day_pre, day_post) in days.items():
            running += day_pre + day_post
            day_rows.append([day, day_pre, day_post, day_pre + day_post, running])
        tables.append(ReportTable(
            'Cost by day',
            [Column('Date', DATE), Column('Pre-development', MONEY), Column('Post-development', MONEY), Column('Total', MONEY),
             Column('Running total', MONEY)],
            day_rows, ['Total', pre, post, pre + post, None],
            note='Days with no cost are left out.',
        ))

    for phase in (Phase.PRE, Phase.POST):
        rows = by_phase[phase]
        tables.append(ReportTable(
            f'{PHASE_NAMES[phase]} costs',
            [Column('Date', DATE), Column('Voucher'), Column('Cost head'), Column('Particulars'), Column('Building'),
             Column('Charged to'), Column('Amount', MONEY), Column('Paid', MONEY), Column('Due', MONEY), Column('Verified')],
            [[c.date, c.voucher_no, f'{_head(c)} / {c.cost_category.name}' if c.cost_category.parent_category_id else c.cost_category.name,
              ' - '.join(x for x in (c.payee, c.description) if x) or None,
              c.project.project_name, _charged_to(c), c.amount, c.paid_amount, c.due_amount,
              'Yes' if c.is_confirmed else 'No'] for c in rows],
            ['Total', '', '', '', '', '', _sum(c.amount for c in rows), _sum(c.paid_amount for c in rows), _sum(c.due_amount for c in rows), ''] if rows else None,
        ))

    heads = OrderedDict()
    for cost in costs:
        key = (cost.phase, _head(cost))
        heads[key] = heads.get(key, ZERO) + cost.amount
    if heads:
        total = pre + post
        tables.append(ReportTable(
            'By cost head',
            [Column('Phase'), Column('Cost head'), Column('Amount', MONEY), Column('Share of the period\'s cost', PERCENT)],
            [[PHASE_NAMES[phase], head, amount, _percent(amount, total)]
             for (phase, head), amount in sorted(heads.items(), key=lambda item: (item[0][0] != Phase.PRE, -item[1]))],
            ['Total', '', total, 100],
        ))
    return [project_line(project, development), period_line(date_from, date_to)], tables
