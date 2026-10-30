from django.contrib.auth.models import User
from django.test import TestCase

from core.testing import make_account, make_project, make_request
from customers.models import Customer
from projects.models import Development, Project
from sales.models import CustomerPayment, FlatSale

from . import builders
from .views import FinanceReportView


class ProjectLevelReportTests(TestCase):
    """A project holds several buildings; reports can cover one building, one whole project, or everything."""

    def setUp(self):
        self.estate = Development.objects.create(name='Estate')
        self.elsewhere = Development.objects.create(name='Elsewhere')
        self.account = make_account()
        self.customer = Customer.objects.create(name='C', phone='01711111111')
        self.tower1, self.flats1 = make_project('Tower 1', floors=1, units=2)
        self.tower2, self.flats2 = make_project('Tower 2', floors=1, units=2)
        self.other, self.flats3 = make_project('Other Site', floors=1, units=2)
        Project.objects.filter(pk__in=[self.tower1.pk, self.tower2.pk]).update(development=self.estate)
        Project.objects.filter(pk=self.other.pk).update(development=self.elsewhere)
        for flats, amount in ((self.flats1, 100), (self.flats2, 200), (self.flats3, 400)):
            sale = FlatSale.objects.create(flat=flats[0], customer=self.customer, sale_date='2026-01-01', sale_value=1200)
            CustomerPayment.objects.create(sale=sale, payment_date='2026-02-01', amount=amount, account=self.account)

    def received(self, tables):
        row = next(t for t in tables if t.title == 'Sales, collection and receivable')
        return row.totals[7]

    def test_a_project_report_covers_all_its_buildings_and_nothing_else(self):
        lines, tables = builders.finance_report(None, self.estate)
        self.assertEqual(self.received(tables), 300)
        self.assertIn('Project: Estate', lines[0])
        table = next(t for t in tables if t.title == 'Sales, collection and receivable')
        self.assertEqual(len(table.rows), 2)

    def test_one_building_wins_over_its_project(self):
        _, tables = builders.finance_report(self.tower2, self.estate)
        self.assertEqual(self.received(tables), 200)

    def test_with_no_filter_everything_is_covered(self):
        self.assertEqual(self.received(builders.finance_report()[1]), 700)

    def test_every_report_accepts_the_project_filter(self):
        for build in (builders.finance_report, builders.profit_loss_report, builders.customer_post_report,
                      builders.flat_wise_report, builders.dues_report):
            lines, tables = build(None, self.estate)
            self.assertTrue(lines and tables, build.__name__)
        lines, tables = builders.periodic_collection_report(None, None, None, self.estate)
        table = next(t for t in tables if t.title == 'Collection by month')
        self.assertEqual(table.totals[2], 300)

    def test_the_project_dropdown_filters_the_screen_and_the_pdf(self):
        user = User.objects.create_superuser('boss', 'b@example.com', 'pw')
        for params in ({'development': self.estate.pk}, {'development': self.estate.pk, 'format': 'pdf'},
                       {'development': self.estate.pk, 'format': 'xlsx'}, {'development': 'abc'}):
            response = FinanceReportView.as_view()(make_request(user, '/', data=params))
            if hasattr(response, 'render'):
                response.render()
            self.assertEqual(response.status_code, 200, params)

    def test_the_flat_wise_report_only_lists_the_projects_flats(self):
        _, tables = builders.flat_wise_report(None, self.estate)
        self.assertEqual(len(tables[0].rows), 4)
