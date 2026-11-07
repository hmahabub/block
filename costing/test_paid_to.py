"""A cost with no supplier says who the payment was given to, typed in by hand."""
import datetime
from io import BytesIO

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from openpyxl import load_workbook

from books.ledger import collect_entries
from core.testing import enter_project, make_account, make_project, unlock_client
from projects.models import Development
from reports.costs import daily_cost_report
from suppliers.models import Supplier

from .forms import DirectCostForm, SharedCostForm
from .models import CostCategory, ProjectCost

DAY = datetime.date(2026, 3, 10)


class PaidToTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser('boss', 'b@example.com', 'pw')
        self.development = Development.objects.create(name='Estate')
        self.building, self.flats = make_project('Tower', floors=1, units=2, development=self.development)
        self.bank = make_account('Bank 1')
        self.category = CostCategory.objects.create(name='Civil', phase='POST')
        self.supplier = Supplier.objects.create(name='Steel Co')

    def data(self, **extra):
        return {'project': self.building.pk, 'cost_category': self.category.pk, 'date': DAY.isoformat(), 'amount': '500',
                'account': self.bank.pk, **extra}

    def make(self, **extra):
        return ProjectCost.objects.create(
            project=self.building, cost_category=self.category, date=DAY, amount=500, account=self.bank, **extra)


class FormTests(PaidToTestCase):
    def test_a_supplier_is_enough(self):
        self.assertTrue(SharedCostForm(data=self.data(supplier=self.supplier.pk)).is_valid())

    def test_with_no_supplier_a_name_must_be_typed(self):
        form = SharedCostForm(data=self.data())
        self.assertFalse(form.is_valid())
        self.assertIn('paid_to', form.errors)
        self.assertFalse(SharedCostForm(data=self.data(paid_to='   ')).is_valid())

    def test_a_typed_name_is_kept(self):
        form = SharedCostForm(data=self.data(paid_to='  Mr. Hasan (labour)  '))
        self.assertTrue(form.is_valid(), form.errors)
        cost = form.save()
        self.assertEqual((cost.paid_to, cost.payee, cost.supplier), ('Mr. Hasan (labour)', 'Mr. Hasan (labour)', None))

    def test_when_a_supplier_is_chosen_the_typed_name_is_dropped(self):
        form = SharedCostForm(data=self.data(supplier=self.supplier.pk, paid_to='Someone else'))
        self.assertTrue(form.is_valid(), form.errors)
        cost = form.save()
        self.assertEqual((cost.paid_to, cost.payee), ('', 'Steel Co'))

    def test_a_direct_flat_cost_follows_the_same_rule(self):
        data = {'flat': self.flats[0].pk, 'cost_category': self.category.pk, 'date': DAY.isoformat(), 'amount': '90', 'account': self.bank.pk}
        self.assertFalse(DirectCostForm(data=data).is_valid())
        self.assertTrue(DirectCostForm(data={**data, 'paid_to': 'Plumber Karim'}).is_valid())

    def test_an_older_cost_that_never_had_a_payee_can_still_be_edited(self):
        old = self.make()
        form = SharedCostForm(data=self.data(amount='550'), instance=old)
        self.assertTrue(form.is_valid(), form.errors)

    def test_but_a_cost_that_has_a_payee_cannot_lose_it(self):
        cost = self.make(paid_to='Mr. Hasan')
        self.assertFalse(SharedCostForm(data=self.data(paid_to=''), instance=cost).is_valid())

    def test_the_payee_is_the_supplier_else_the_typed_name(self):
        self.assertEqual(self.make(supplier=self.supplier).payee, 'Steel Co')
        self.assertEqual(self.make(paid_to='Mr. Hasan').payee, 'Mr. Hasan')
        self.assertEqual(self.make().payee, '')


class ScreenTests(PaidToTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.user)
        unlock_client(self.client)
        enter_project(self.client, self.development)
        self.typed = self.make(paid_to='Mr. Hasan (labour)', description='Wages')
        self.listed = self.make(supplier=self.supplier)

    def test_the_form_has_the_field_and_hides_it_while_a_supplier_is_chosen(self):
        page = self.client.get(reverse('costing:cost-create-shared')).content.decode()
        self.assertIn('id_paid_to', page)
        self.assertIn('paid-to-wrap', page)

    def test_saving_a_cost_through_the_page(self):
        response = self.client.post(reverse('costing:cost-create-shared'), self.data(paid_to='Mr. Rahim'))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(ProjectCost.objects.filter(paid_to='Mr. Rahim').exists())

    def test_the_cost_page_the_list_and_the_voucher_show_the_name(self):
        for name in ('costing:cost-detail', 'costing:cost-voucher'):
            self.assertIn('Mr. Hasan (labour)', self.client.get(reverse(name, args=[self.typed.pk])).content.decode(), name)
        listing = self.client.get(reverse('costing:cost-list')).content.decode()
        self.assertIn('Mr. Hasan (labour)', listing)
        self.assertIn('Steel Co', listing)
        self.assertIn('Paid to', listing)

    def test_the_list_can_be_searched_by_the_typed_name(self):
        response = self.client.get(reverse('costing:cost-list'), {'q': 'hasan'})
        self.assertEqual([c.pk for c in response.context['object_list']], [self.typed.pk])

    def test_the_cost_downloads_carry_the_name(self):
        xlsx = self.client.get(reverse('costing:cost-report-xlsx'))
        cells = {str(c.value) for row in load_workbook(BytesIO(xlsx.content)).active.iter_rows() for c in row}
        self.assertIn('Mr. Hasan (labour)', cells)
        self.assertIn('Paid to', cells)
        self.assertTrue(self.client.get(reverse('costing:cost-report-pdf')).content.startswith(b'%PDF'))

    def test_the_book_and_the_daily_reports_name_who_was_paid(self):
        entry = [e for e in collect_entries(development=self.development) if e.key == f'pc:{self.typed.pk}'][0]
        self.assertIn('Mr. Hasan (labour)', entry.description)
        _, tables = daily_cost_report(None, self.development, DAY, DAY)
        particulars = [r[3] for r in [t for t in tables if t.title == 'Post-development costs'][0].rows]
        self.assertIn('Mr. Hasan (labour) - Wages', particulars)
        self.assertIn('Steel Co', particulars)

    def test_the_supplier_ledger_is_unaffected(self):
        page = self.client.get(reverse('suppliers:ledger', args=[self.supplier.pk])).content.decode()
        self.assertNotIn('Mr. Hasan', page)

    def test_the_change_is_in_the_audit_trail(self):
        from activity_log.models import ActivityLog

        self.assertTrue(ActivityLog.objects.filter(model_name='ProjectCost', object_id=str(self.typed.pk)).exists())
