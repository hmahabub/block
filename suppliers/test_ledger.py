import io
import time
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from openpyxl import load_workbook

from core.testing import make_account, make_project, make_request
from costing.models import CostCategory, ProjectCost

from .models import Supplier
from .views import SupplierDetailView, SupplierLedgerView

D = Decimal
UNLOCKED = dict(session={'reauth_until': time.time() + 600, 'reauth_token': 'tok'}, cookies={'daj_unlocked': 'tok'})


class SupplierLedgerTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser('boss', 'b@example.com', 'pw')
        self.tower1, _ = make_project('Tower 1', floors=1, units=1)
        self.tower2, _ = make_project('Tower 2', floors=1, units=1)
        self.account = make_account('Bank 1')
        self.supplier = Supplier.objects.create(name='Rahman Traders', tin='123456789012')
        self.other = Supplier.objects.create(name='Someone Else')
        self.civil = CostCategory.objects.create(name='Civil')
        self.land = CostCategory.objects.create(name='Land', phase=CostCategory.CategoryPhase.PRE)

    def pay(self, amount, date, project=None, category=None, supplier=None, **extra):
        return ProjectCost.objects.create(
            project=project or self.tower1, cost_category=category or self.civil, supplier=supplier or self.supplier,
            date=date, amount=amount, account=self.account, **extra,
        )

    def ledger(self, locked=False, **params):
        extra = {} if locked else UNLOCKED
        request = make_request(self.user, '/', data=params, **extra)
        view = SupplierLedgerView()
        view.setup(request, pk=self.supplier.pk)
        view.kwargs = {'pk': self.supplier.pk}
        view.object = self.supplier
        return view, request

    def data(self, **params):
        view, request = self.ledger(**params)
        return view.ledger()

    def test_the_ledger_lists_only_this_suppliers_payments_oldest_first(self):
        self.pay(300, '2026-02-01')
        self.pay(100, '2026-01-01')
        self.pay(999, '2026-01-15', supplier=self.other)
        data = self.data()
        self.assertEqual([c.amount for c in data['rows']], [100, 300])

    def test_a_running_total_builds_up_line_by_line(self):
        for amount, date in ((100, '2026-01-01'), (250, '2026-01-10'), (50, '2026-02-01')):
            self.pay(amount, date)
        data = self.data()
        self.assertEqual([c.running_total for c in data['rows']], [100, 350, 400])
        self.assertEqual((data['period_total'], data['closing_total'], data['brought_forward']), (400, 400, 0))

    def test_a_period_carries_forward_what_was_paid_before(self):
        self.pay(100, '2026-01-01')
        self.pay(250, '2026-02-10')
        self.pay(50, '2026-03-01')
        data = self.data(date_from='2026-02-01', date_to='2026-02-28')
        self.assertEqual(data['brought_forward'], 100)
        self.assertEqual([c.running_total for c in data['rows']], [350])
        self.assertEqual((data['period_total'], data['closing_total']), (250, 350))

    def test_filter_by_building_and_phase(self):
        self.pay(100, '2026-01-01', project=self.tower1)
        self.pay(200, '2026-01-02', project=self.tower2)
        self.pay(400, '2026-01-03', project=self.tower1, category=self.land)
        self.assertEqual(self.data(project=self.tower2.pk)['period_total'], 200)
        self.assertEqual(self.data(phase='PRE')['period_total'], 400)
        self.assertEqual(self.data(project=self.tower1.pk, phase='POST')['period_total'], 100)
        self.assertEqual(self.data(project=self.tower1.pk, phase='POST')['closing_total'], 100)

    def test_filters_carry_forward_only_matching_payments(self):
        self.pay(100, '2026-01-01', project=self.tower1)
        self.pay(900, '2026-01-02', project=self.tower2)
        self.pay(50, '2026-02-01', project=self.tower1)
        data = self.data(project=self.tower1.pk, date_from='2026-02-01')
        self.assertEqual((data['brought_forward'], data['closing_total']), (100, 150))

    def test_bad_filters_are_ignored(self):
        self.pay(100, '2026-01-01')
        data = self.data(project='abc', phase='x', date_from='nonsense', date_to='31/12/2026')
        self.assertEqual(len(data['rows']), 1)

    def test_by_building_totals(self):
        self.pay(100, '2026-01-01', project=self.tower1)
        self.pay(200, '2026-01-02', project=self.tower2)
        self.pay(50, '2026-01-03', project=self.tower2)
        totals = {b.project_name: t for b, t in self.data()['by_building']}
        self.assertEqual(totals, {'Tower 1': 100, 'Tower 2': 250})

    def test_a_supplier_with_no_payments_has_an_empty_ledger(self):
        data = self.data()
        self.assertEqual((data['rows'], data['closing_total']), ([], 0))

    def test_the_page_renders_with_the_figures(self):
        self.pay(1234, '2026-01-01', description='Cement', reference_no='B-9')
        view, request = self.ledger()
        response = SupplierLedgerView.as_view()(request, pk=self.supplier.pk)
        response.render()
        html = response.content.decode()
        for expected in ('Rahman Traders', '1,234.00', 'CV-', 'Cement', 'Tower 1', 'Excel'):
            self.assertIn(expected, html)

    def test_the_ledger_is_hidden_while_the_screens_are_locked(self):
        self.pay(1234, '2026-01-01')
        request = make_request(self.user, '/')
        response = SupplierLedgerView.as_view()(request, pk=self.supplier.pk)
        response.render()
        html = response.content.decode()
        self.assertNotIn('1,234.00', html)
        self.assertIn('Enter your password', html)

    def test_the_excel_download_has_real_numbers_and_the_running_total(self):
        self.pay(100, '2026-01-01')
        self.pay(250, '2026-01-10')
        request = make_request(self.user, '/', data={'format': 'xlsx'}, **UNLOCKED)
        response = SupplierLedgerView.as_view()(request, pk=self.supplier.pk)
        self.assertIn('spreadsheetml', response['Content-Type'])
        sheet = load_workbook(io.BytesIO(response.content)).active
        cells = [c.value for row in sheet.iter_rows() for c in row]
        for expected in (100.0, 250.0, 350.0, 'Supplier: Rahman Traders (' + self.supplier.supplier_code + ')', 'TIN: 123456789012'):
            self.assertIn(expected, cells)

    def test_the_excel_is_refused_while_locked(self):
        self.pay(100, '2026-01-01')
        request = make_request(self.user, '/', data={'format': 'xlsx'})
        response = SupplierLedgerView.as_view()(request, pk=self.supplier.pk)
        self.assertNotIn('spreadsheetml', response.get('Content-Type', ''))

    def test_confirmed_payments_are_marked(self):
        cost = self.pay(100, '2026-01-01')
        cost.confirm(self.user)
        row = self.data()['rows'][0]
        self.assertTrue(row.is_confirmed)

    def test_the_supplier_page_links_to_the_ledger_and_hides_costs_when_locked(self):
        self.pay(7777, '2026-01-01')
        locked = SupplierDetailView.as_view()(make_request(self.user, '/'), pk=self.supplier.pk)
        locked.render()
        self.assertIn('/ledger/', locked.content.decode())
        self.assertNotIn('7,777.00', locked.content.decode())
        unlocked = SupplierDetailView.as_view()(make_request(self.user, '/', **UNLOCKED), pk=self.supplier.pk)
        unlocked.render()
        self.assertIn('7,777.00', unlocked.content.decode())
