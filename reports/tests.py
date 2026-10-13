import datetime
from decimal import Decimal

from django.contrib.auth.models import AnonymousUser, User
from django.test import RequestFactory, TestCase

from core.formatting import format_cell
from core.testing import make_account, make_project
from costing.models import CostCategory, ProjectCost
from customers.models import Customer
from sales.models import CustomerPayment, FlatSale, HonorariumPayment, Reference

from . import builders
from .tables import Column, ReportTable
from .views import (
    CustomerPostReportView,
    DuesReportView,
    FinanceReportView,
    FlatWiseReportView,
    PeriodicCollectionReportView,
    ProfitLossReportView,
)

D = Decimal


class ReportData(TestCase):
    """Base 1000, quoted 1200, parking 100, four flats.

    A1 (Rahim): sale 1500 with parking -> base 1100, honorarium 400, reg 50, net 1550; paid 800 in two payments.
    B1 (Karim): sale 1000, paid in full (1000).
    A2 (Salma): sale 1200, paid 600, then cancelled with a 50% refund (keeps 300).
    B2 stays free.
    Costs: land (pre-development) 700, civil (post-development) 400 = 100 per flat.
    """

    def setUp(self):
        self.project, self.flats = make_project('Tower')
        self.bank = make_account('Bank 1', opening_balance=5000)
        self.ref = Reference.objects.create(name='Ref')
        self.rahim = Customer.objects.create(title='MR', name='Rahim', phone='01711000001')
        self.karim = Customer.objects.create(name='Karim', phone='01711000002')
        self.salma = Customer.objects.create(name='Salma', phone='01711000003')

        self.sale_a = FlatSale.objects.create(
            flat=self.flats[0], customer=self.rahim, ref=self.ref, sale_date='2026-01-01',
            with_parking=True, sale_value=1500, reg_value=50,
        )
        self.sale_b = FlatSale.objects.create(flat=self.flats[1], customer=self.karim, sale_date='2026-01-02', sale_value=1000)
        self.sale_c = FlatSale.objects.create(flat=self.flats[2], customer=self.salma, sale_date='2026-01-03', sale_value=1200)

        self.pay(self.sale_a, 500, '2026-01-10')
        self.pay(self.sale_a, 300, '2026-02-10')
        self.pay(self.sale_b, 1000, '2026-02-15')
        self.pay(self.sale_c, 600, '2026-02-20')
        self.sale_c.cancel(50)
        self.sale_c.save()

        land = CostCategory.objects.create(name='Land', phase=CostCategory.CategoryPhase.PRE)
        civil = CostCategory.objects.create(name='Civil')
        ProjectCost.objects.create(project=self.project, cost_category=land, date='2026-01-05', amount=700, account=self.bank)
        ProjectCost.objects.create(project=self.project, cost_category=civil, date='2026-01-06', amount=400, account=self.bank)

    def pay(self, sale, amount, date):
        return CustomerPayment.objects.create(sale=sale, payment_date=date, amount=amount, account=self.bank)

    def rows(self, tables, title):
        return next(t for t in tables if t.title == title).rows

    def table(self, tables, title):
        return next(t for t in tables if t.title == title)


class FinanceReportTests(ReportData):
    def test_sales_and_collection(self):
        _, tables = builders.finance_report(self.project)
        row = self.rows(tables, 'Sales, collection and receivable')[0]
        flats, active, sale_value, honorarium, reg, net, received, receivable = row[1:]
        self.assertEqual((flats, active), (4, 2))
        self.assertEqual((sale_value, honorarium, reg, net), (2500, 400, 50, 2550))
        self.assertEqual((received, receivable), (2400, 750))

    def test_cost_and_payable(self):
        _, tables = builders.finance_report(self.project)
        _, pre, post, total, honorarium_due, refund_due, payable = self.rows(tables, 'Cost and payable')[0]
        self.assertEqual((pre, post, total), (700, 400, 1100))
        self.assertEqual((honorarium_due, refund_due, payable), (400, 300, 700))

    def test_payable_falls_as_honorarium_and_refunds_are_paid(self):
        HonorariumPayment.objects.create(sale=self.sale_a, date='2026-03-01', amount=150, account=self.bank)
        _, tables = builders.finance_report(self.project)
        self.assertEqual(self.rows(tables, 'Cost and payable')[0][4], 250)

    def test_totals_row_adds_the_projects(self):
        other, other_flats = make_project('Other')
        _, tables = builders.finance_report()
        table = self.table(tables, 'Sales, collection and receivable')
        self.assertEqual(len(table.rows), 2)
        self.assertEqual(table.totals[1], 8)  # flats

    def test_money_in_hand_lists_the_accounts(self):
        _, tables = builders.finance_report(self.project)
        row = self.rows(tables, 'Money in hand (accounts)')[0]
        self.assertEqual((row[0], row[2], row[3]), ('Bank 1', 2400, 1100))
        self.assertEqual(row[5], 5000 + 2400 - 1100)


class ProfitLossReportTests(ReportData):
    def test_pre_development_profit_uses_base_price_not_sale_value(self):
        _, tables = builders.profit_loss_report(self.project)
        row = self.rows(tables, 'Pre-development profit / loss, collection and due')[0]
        _, sold, base_earned, kept, pre_cost, result, net, collected, pct, due, honorarium, hon_paid = row
        self.assertEqual((sold, base_earned), (2, 2100))     # 1100 + 1000: the honorarium is not the company's
        self.assertEqual((kept, pre_cost), (300, 700))       # money kept on the 50% cancellation
        self.assertEqual(result, 1700)                       # 2100 + 300 - 700
        self.assertEqual((net, collected, due), (2550, 1800, 750))
        self.assertAlmostEqual(float(pct), 1800 / 2550 * 100, places=3)
        self.assertEqual((honorarium, hon_paid), (400, 0))

    def test_post_development_cost_does_not_reduce_the_pre_development_result(self):
        _, tables = builders.profit_loss_report(self.project)
        result = self.rows(tables, 'Pre-development profit / loss, collection and due')[0][5]
        ProjectCost.objects.create(
            project=self.project, cost_category=CostCategory.objects.get(name='Civil'), date='2026-03-01', amount=9999,
        )
        _, tables = builders.profit_loss_report(self.project)
        self.assertEqual(self.rows(tables, 'Pre-development profit / loss, collection and due')[0][5], result)

    def test_a_loss_is_negative(self):
        ProjectCost.objects.create(
            project=self.project, cost_category=CostCategory.objects.get(name='Land'), date='2026-03-01', amount=5000,
        )
        _, tables = builders.profit_loss_report(self.project)
        self.assertLess(self.rows(tables, 'Pre-development profit / loss, collection and due')[0][5], 0)

    def test_pre_development_cost_is_listed_by_head(self):
        _, tables = builders.profit_loss_report(self.project)
        self.assertEqual(self.rows(tables, 'Pre-development cost by head'), [['Land', 700]])


class PeriodicCollectionTests(ReportData):
    def test_collection_by_month_with_a_running_total(self):
        _, tables = builders.periodic_collection_report(self.project)
        months = self.rows(tables, 'Collection by month')
        self.assertEqual(months, [['January 2026', 1, 500, 500], ['February 2026', 3, 1900, 2400]])

    def test_the_period_limits_what_is_counted(self):
        _, tables = builders.periodic_collection_report(self.project, date_from=datetime.date(2026, 2, 1))
        table = self.table(tables, 'Collection by month')
        self.assertEqual(table.totals[2], 1900)

    def test_collection_by_customer_and_by_account(self):
        _, tables = builders.periodic_collection_report(self.project)
        customers = {r[0]: r for r in self.rows(tables, 'Collection by customer')}
        self.assertEqual((customers['Rahim'][2], customers['Rahim'][3]), (2, 800))
        self.assertEqual(self.rows(tables, 'Collection by account'), [['Bank 1', 4, 2400]])

    def test_an_empty_period_gives_empty_tables(self):
        import datetime
        _, tables = builders.periodic_collection_report(date_from=datetime.date(2030, 1, 1))
        self.assertEqual(self.table(tables, 'Collection by month').rows, [])


class CustomerPostReportTests(ReportData):
    def test_each_active_customer_with_their_cost_share(self):
        _, tables = builders.customer_post_report(self.project)
        rows = {r[0]: r for r in self.rows(tables, 'Customer balance, cost, receivable and payable')}
        self.assertEqual(set(rows), {'Mr. Rahim', 'Karim'})  # the cancelled customer is not an owner
        _, flat, project, net, received, receivable, balance, share, after = rows['Mr. Rahim']
        self.assertEqual((flat, net, received, receivable, balance), ('A1', 1550, 800, 750, 0))
        self.assertEqual((share, after), (100, -100))

    def test_extra_payments_become_customer_balance_that_offsets_the_cost_share(self):
        self.pay(self.sale_b, 400, '2026-03-01')
        _, tables = builders.customer_post_report(self.project)
        row = next(r for r in self.rows(tables, 'Customer balance, cost, receivable and payable') if r[0] == 'Karim')
        self.assertEqual((row[6], row[7], row[8]), (400, 100, 300))

    def test_unsold_flats_and_refunds_are_summarised(self):
        _, tables = builders.customer_post_report(self.project)
        other = self.rows(tables, 'Other post-development items')
        self.assertEqual(other[0][1:], [2, 200])   # the cancelled flat and the free one, 100 each
        self.assertEqual(other[1][2], 300)         # refund still owed to the cancelled customer


class FlatWiseAndDuesTests(ReportData):
    def test_flat_wise_has_no_profit_column_and_shows_the_cost_share(self):
        _, tables = builders.flat_wise_report(self.project)
        labels = [c.label for c in tables[0].columns]
        self.assertNotIn('Profit', ' '.join(labels))
        row = next(r for r in tables[0].rows if r[0] == 'A1')
        self.assertEqual((row[3], row[4], row[9], row[11]), ('Rahim', 1500, 100, 100))

    def test_dues_lists_only_active_bookings_with_a_balance(self):
        _, tables = builders.dues_report(self.project)
        self.assertEqual([r[0] for r in tables[0].rows], ['Rahim'])
        self.assertEqual(tables[0].totals[5], 750)


class ReportOutputTests(ReportData):
    views = (
        FinanceReportView, PeriodicCollectionReportView, ProfitLossReportView,
        CustomerPostReportView, FlatWiseReportView, DuesReportView,
    )

    def get(self, view, user=None, **params):
        request = RequestFactory().get('/', params)
        request.user = user or User.objects.create_superuser(f'u{User.objects.count()}', 'u@example.com', 'pw')
        return view.as_view()(request)

    def test_every_report_renders_as_a_pdf(self):
        for view in self.views:
            response = self.get(view, format='pdf')
            self.assertEqual(response.status_code, 200, view)
            self.assertTrue(response.content.startswith(b'%PDF'), view)
            self.assertIn('application/pdf', response['Content-Type'])

    def test_every_report_renders_on_screen(self):
        for view in self.views:
            response = self.get(view)
            response.render()
            self.assertEqual(response.status_code, 200, view)
            self.assertIn(b'<table', response.content, view)

    def test_reports_render_with_no_data_at_all(self):
        CustomerPayment.objects.all().delete()
        FlatSale.objects.all().delete()
        ProjectCost.objects.all().delete()
        for view in self.views:
            self.assertTrue(self.get(view, format='pdf').content.startswith(b'%PDF'), view)

    def test_the_project_filter_applies(self):
        other, _ = make_project('Other')
        response = self.get(FinanceReportView, project=other.pk)
        response.render()
        self.assertIn(b'ABP-002 Other', response.content)
        self.assertNotIn(b'ABP-001 Tower', response.content)

    def test_bad_dates_and_projects_are_ignored(self):
        response = self.get(PeriodicCollectionReportView, project='x', date_from='nope', date_to='31/12/2026')
        response.render()
        self.assertEqual(response.status_code, 200)

    def test_login_is_required(self):
        request = RequestFactory().get('/')
        request.user = AnonymousUser()
        self.assertEqual(FinanceReportView.as_view()(request).status_code, 302)


class FormattingTests(TestCase):
    def test_cells(self):
        self.assertEqual(format_cell(1234567.5, 'money'), '1,234,567.50')
        self.assertEqual(format_cell(D('12.345'), 'percent'), '12.3%')
        self.assertEqual(format_cell(12, 'int'), '12')
        self.assertEqual(format_cell(None, 'money'), '-')
        self.assertEqual(format_cell('Hello'), 'Hello')

    def test_table_formats_each_column_by_its_kind(self):
        table = ReportTable('T', [Column('Name'), Column('Amount', 'money')], [['A', 1000]], ['Total', 1000])
        self.assertEqual(table.cells, [[('A', False), ('1,000.00', True)]])
        self.assertEqual(table.total_cells[1], ('1,000.00', True))
