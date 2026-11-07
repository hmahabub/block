"""The daily cost report: pre-development and post-development cost apart."""
import datetime
from decimal import Decimal
from io import BytesIO

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from openpyxl import load_workbook

from core.testing import enter_project, make_account, make_project, unlock_client
from costing.models import CostCategory, ProjectCost
from projects.models import Development
from suppliers.models import Supplier

from .costs import daily_cost_report

D = Decimal
DAY = datetime.date(2026, 3, 10)
NEXT = DAY + datetime.timedelta(days=1)


class CostReportTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser('boss', 'b@example.com', 'pw')
        self.development = Development.objects.create(name='Estate')
        self.building, self.flats = make_project('Tower', floors=1, units=2, development=self.development)
        self.bank = make_account('Bank 1')
        land = CostCategory.objects.create(name='Land Related Costs', phase='PRE')
        self.land_value = CostCategory.objects.create(name='Land Value', parent_category=land)
        civil = CostCategory.objects.create(name='Structural', phase='POST')
        self.rod = CostCategory.objects.create(name='Rod', parent_category=civil)
        self.supplier = Supplier.objects.create(name='Steel Co')
        self.pre = self.cost(self.land_value, 4000)
        self.post = self.cost(self.rod, 900, supplier=self.supplier, description='Rod 12mm')
        self.direct = self.cost(self.rod, 100, flat=self.flats[0])
        self.next_day = self.cost(self.rod, 70, date=NEXT)

    def cost(self, category, amount, date=DAY, **extra):
        return ProjectCost.objects.create(project=self.building, cost_category=category, date=date, amount=amount, account=self.bank, **extra)

    def table(self, tables, title):
        return [t for t in tables if t.title == title][0]

    def login(self):
        self.client.force_login(self.user)
        unlock_client(self.client)
        enter_project(self.client, self.development)


class ReportContentTests(CostReportTestCase):
    def report(self, date_from=DAY, date_to=DAY):
        return daily_cost_report(None, self.development, date_from, date_to)

    def test_pre_and_post_development_are_kept_apart(self):
        _, tables = self.report()
        totals = self.table(tables, 'Totals')
        self.assertEqual([(r[0], r[1], r[2]) for r in totals.rows], [('Pre-development', 1, 4000), ('Post-development', 2, 1000)])
        self.assertEqual(totals.totals[:3], ['Total', 3, 5000])

    def test_each_phase_lists_its_vouchers(self):
        _, tables = self.report()
        pre, post = self.table(tables, 'Pre-development costs'), self.table(tables, 'Post-development costs')
        self.assertEqual([r[1] for r in pre.rows], [self.pre.voucher_no])
        self.assertEqual({r[1] for r in post.rows}, {self.post.voucher_no, self.direct.voucher_no})
        self.assertEqual((pre.totals[6], post.totals[6]), (4000, 1000))

    def test_the_particulars_charged_to_and_head_are_shown(self):
        _, tables = self.report()
        post = {r[1]: r for r in self.table(tables, 'Post-development costs').rows}
        shared, direct = post[self.post.voucher_no], post[self.direct.voucher_no]
        self.assertEqual(shared[2], 'Structural / Rod')
        self.assertEqual(shared[3], 'Steel Co - Rod 12mm')
        self.assertEqual((shared[5], direct[5]), ('All flat owners', f'Flat {self.flats[0].flat_no}'))
        self.assertEqual(self.table(tables, 'Pre-development costs').rows[0][5], 'Company')

    def test_only_the_days_costs_are_in_it(self):
        _, tables = self.report()
        vouchers = {r[1] for t in tables if t.title.endswith(' costs') for r in t.rows}
        self.assertNotIn(self.next_day.voucher_no, vouchers)

    def test_a_period_adds_a_day_by_day_table_with_a_running_total(self):
        _, tables = self.report(DAY, NEXT)
        days = self.table(tables, 'Cost by day')
        self.assertEqual([(r[0], r[1], r[2], r[3], r[4]) for r in days.rows], [(DAY, 4000, 1000, 5000, 5000), (NEXT, 0, 70, 70, 5070)])
        self.assertEqual(days.totals[1:4], [4000, 1070, 5070])

    def test_a_single_day_has_no_day_table(self):
        _, tables = self.report()
        self.assertNotIn('Cost by day', [t.title for t in tables])

    def test_the_heads_with_their_share(self):
        _, tables = self.report()
        heads = self.table(tables, 'By cost head')
        self.assertEqual([(r[0], r[1], r[2]) for r in heads.rows], [('Pre-development', 'Land Related Costs', 4000), ('Post-development', 'Structural', 1000)])
        self.assertAlmostEqual(float(heads.rows[0][3]), 80.0)

    def test_unverified_costs_are_marked(self):
        self.pre.confirm(self.user)
        _, tables = self.report()
        verified = {r[1]: r[9] for r in self.table(tables, 'Pre-development costs').rows}
        self.assertEqual(verified[self.pre.voucher_no], 'Yes')
        self.assertEqual({r[9] for r in self.table(tables, 'Post-development costs').rows}, {'No'})

    def test_a_day_with_no_cost_gives_empty_tables(self):
        _, tables = self.report(DAY + datetime.timedelta(days=30), DAY + datetime.timedelta(days=30))
        self.assertEqual(self.table(tables, 'Totals').totals[2], 0)
        self.assertNotIn('By cost head', [t.title for t in tables])

    def test_another_building_can_be_picked_and_other_projects_are_left_out(self):
        other = Development.objects.create(name='Other')
        far, far_flats = make_project('Villa', floors=1, units=1, development=other)
        ProjectCost.objects.create(project=far, cost_category=self.rod, date=DAY, amount=999, account=self.bank)
        _, tables = self.report()
        self.assertEqual(self.table(tables, 'Totals').totals[2], 5000)
        _, only = daily_cost_report(self.building, None, DAY, DAY)
        self.assertEqual(self.table(only, 'Totals').totals[2], 5000)


class ReportScreenTests(CostReportTestCase):
    def setUp(self):
        super().setUp()
        self.login()

    def test_it_opens_on_today(self):
        today_cost = self.cost(self.rod, 55, date=datetime.date.today())
        response = self.client.get(reverse('reports:daily-costs'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual((response.context['date_from'], response.context['date_to']), (datetime.date.today(),) * 2)
        self.assertIn(today_cost.voucher_no, response.content.decode())
        self.assertNotIn(self.pre.voucher_no, response.content.decode())

    def test_a_chosen_day(self):
        page = self.client.get(reverse('reports:daily-costs'), {'date_from': DAY.isoformat(), 'date_to': DAY.isoformat()}).content.decode()
        self.assertIn('Pre-development costs', page)
        self.assertIn('Post-development costs', page)
        self.assertIn(self.pre.voucher_no, page)
        self.assertIn(self.post.voucher_no, page)

    def test_a_lone_date_means_that_day(self):
        response = self.client.get(reverse('reports:daily-costs'), {'date_from': DAY.isoformat()})
        self.assertEqual((response.context['date_from'], response.context['date_to']), (DAY, DAY))

    def test_pdf_and_excel(self):
        query = {'date_from': DAY.isoformat(), 'date_to': NEXT.isoformat()}
        pdf = self.client.get(reverse('reports:daily-costs'), {**query, 'format': 'pdf'})
        self.assertTrue(pdf.content.startswith(b'%PDF'))
        xlsx = self.client.get(reverse('reports:daily-costs'), {**query, 'format': 'xlsx'})
        cells = {str(c.value) for row in load_workbook(BytesIO(xlsx.content)).active.iter_rows() for c in row}
        self.assertIn(self.pre.voucher_no, cells)
        self.assertIn('Pre-development', cells)

    def test_it_is_always_about_the_open_project(self):
        other = Development.objects.create(name='Other')
        far, _ = make_project('Villa', floors=1, units=1, development=other)
        ProjectCost.objects.create(project=far, cost_category=self.rod, date=DAY, amount=999, account=self.bank)
        response = self.client.get(reverse('reports:daily-costs'), {'date_from': DAY.isoformat(), 'development': other.pk})
        self.assertNotIn('999.00', response.content.decode())

    def test_it_needs_a_project(self):
        self.client.post(reverse('exit-project'))
        self.assertRedirects(self.client.get(reverse('reports:daily-costs')), reverse('home'))

    def test_it_is_in_the_menu_and_the_report_centre(self):
        for url in (reverse('home'), reverse('reports:index')):
            self.assertIn(reverse('reports:daily-costs'), self.client.get(url).content.decode())
