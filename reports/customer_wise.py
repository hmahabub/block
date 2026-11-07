"""The customer-wise report: for each customer who booked a flat in the project, what they booked and where they stand."""
from collections import OrderedDict
from decimal import Decimal

from core.formatting import DATE, INT, MONEY, PERCENT
from installments.services import OVERDUE, allocate, due_total, overdue_total
from sales.models import FlatSale

from .builders import _projects, _sum, project_line
from .tables import Column, ReportTable

ZERO = Decimal('0')


def _bookings(project, development):
    return list(
        FlatSale.objects.filter(project__in=_projects(project, development))
        .select_related('customer', 'flat', 'project', 'ref')
        .prefetch_related('installment_charges__installment', 'installment_charges__invoice', 'refund_payments', 'payments')
        .order_by('customer__name', 'customer_id', 'project__project_name', 'flat__flat_no')
    )


def customer_wise_report(project=None, development=None):
    bookings = _bookings(project, development)
    active = [s for s in bookings if s.status != FlatSale.Status.CANCELLED]
    cancelled = [s for s in bookings if s.status == FlatSale.Status.CANCELLED]

    installments = {s.pk: allocate(s, list(s.installment_charges.all()), list(s.payments.all())) for s in active}
    cost = {s.pk: s.flat.total_cost for s in active}

    customers = OrderedDict()
    for sale in active:
        customers.setdefault(sale.customer_id, []).append(sale)

    summary = []
    for sales in customers.values():
        customer = sales[0].customer
        rows = [row for s in sales for row in installments[s.pk]]
        summary.append([
            customer.customer_code, customer.name, customer.phone, len(sales), ', '.join(s.flat.flat_no for s in sales),
            _sum(s.sale_value for s in sales), _sum(s.net_value for s in sales), _sum(s.received_amount for s in sales),
            _sum(s.receivable_amount for s in sales), _sum(cost[s.pk] for s in sales),
            _sum(r.charge.amount for r in rows), due_total(rows), overdue_total(rows),
        ])
    summary_totals = ['Total', '', '', _sum(r[3] for r in summary), ''] + [_sum(r[i] for r in summary) for i in range(5, 13)] if summary else None
    tables = [ReportTable(
        'Customer summary',
        [Column('Customer ID'), Column('Customer'), Column('Phone'), Column('Flats', INT), Column('Flat nos.'),
         Column('Sale value', MONEY), Column('Net value', MONEY), Column('Received', MONEY), Column('Receivable', MONEY),
         Column('Post-dev cost', MONEY), Column('Installments charged', MONEY), Column('Installments due', MONEY),
         Column('Overdue', MONEY)],
        summary, summary_totals,
        note='Only customers who booked a flat in this project are listed. Net value = sale value + registration cost; '
             'receivable = net value - received. Post-development cost is the customer\'s equal share of the building\'s cost '
             'plus any cost recorded against the flat. Installments due is what has been called for and not yet paid.',
    )]

    details = [[
        s.customer.name, s.sale_no, s.sale_date, s.project.project_name, s.flat.flat_no, s.flat.floor_no,
        s.flat.get_flat_type_display(), s.flat.saleable_area, s.flat.parking_lot if s.with_parking else 'Not taken',
        s.get_status_display(), s.registered_on,
    ] for s in active]
    tables.append(ReportTable(
        'Flat booking details',
        [Column('Customer'), Column('Sale no.'), Column('Booked on', DATE), Column('Building'), Column('Flat'), Column('Floor', INT),
         Column('Type'), Column('Area (sqft)', MONEY), Column('Parking lot'), Column('Status'), Column('Registered on', DATE)],
        details,
    ))

    money_rows = [[
        s.customer.name, s.flat.flat_no, s.flat_sale_value, s.parking_sale_value if s.with_parking else None, s.sale_value, s.reg_value,
        s.net_value, s.received_amount, s.receivable_amount, cost[s.pk], s.customer_balance,
    ] for s in active]
    tables.append(ReportTable(
        'Sales, payments and cost by booking',
        [Column('Customer'), Column('Flat'), Column('Flat sale value', MONEY), Column('Parking sale value', MONEY),
         Column('Sale value', MONEY), Column('Reg value', MONEY), Column('Net value', MONEY), Column('Received', MONEY),
         Column('Receivable', MONEY), Column('Post-dev cost', MONEY), Column('Credit (paid in excess)', MONEY)],
        money_rows,
        ['Total', ''] + [_sum((r[i] or ZERO) for r in money_rows) for i in range(2, 11)] if money_rows else None,
    ))

    installment_rows = [[
        s.customer.name, s.flat.flat_no, row.installment.title, row.installment.due_date, row.charge.amount, row.paid, row.due, row.status,
    ] for s in active for row in installments[s.pk]]
    tables.append(ReportTable(
        'Installments by booking',
        [Column('Customer'), Column('Flat'), Column('Installment'), Column('Deadline', DATE), Column('Amount', MONEY),
         Column('Paid', MONEY), Column('Due', MONEY), Column('Status')],
        installment_rows,
        ['Total', '', '', '', _sum(r[4] for r in installment_rows), _sum(r[5] for r in installment_rows),
         _sum(r[6] for r in installment_rows), ''] if installment_rows else None,
        note='Payments received after a booking\'s first installment was issued pay its installments, earliest deadline first.',
    ))

    if cancelled:
        cancelled_rows = [[
            s.customer.name, s.sale_no, s.flat.flat_no, s.cancelled_on, s.received_amount, s.refund_percent, s.refund_amount,
            s.refund_paid, s.refund_due,
        ] for s in cancelled]
        tables.append(ReportTable(
            'Cancelled bookings (not in the tables above)',
            [Column('Customer'), Column('Sale no.'), Column('Flat'), Column('Cancelled on', DATE), Column('Received', MONEY),
             Column('Refund %', PERCENT), Column('Refund', MONEY), Column('Refund paid', MONEY), Column('Refund due', MONEY)],
            cancelled_rows,
            ['Total', '', '', '', _sum(r[4] for r in cancelled_rows), None, _sum(r[6] for r in cancelled_rows),
             _sum(r[7] for r in cancelled_rows), _sum(r[8] for r in cancelled_rows)],
        ))
    return [project_line(project, development), 'Customers who booked a flat in the project'], tables
