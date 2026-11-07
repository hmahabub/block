"""A cost is a voucher; payments are made under it, wholly or in parts, and each payment goes into the book."""
import datetime
from decimal import Decimal

from django.contrib.auth.models import Permission, User
from django.test import TestCase
from django.urls import reverse

from books.ledger import collect_entries, confirm_entries, pending_count
from core.testing import enter_project, make_account, make_project, unlock_client
from customers.models import Customer
from projects.models import Development
from reports.builders import finance_report
from reports.costs import daily_cost_report
from reports.profitability import profitability_report
from sales.models import FlatSale, HonorariumPayment
from suppliers.models import Supplier

from .forms import CostPaymentForm, DirectCostForm, SharedCostForm
from .models import CostCategory, CostPayment, ProjectCost

D = Decimal
DAY = datetime.date(2026, 3, 10)


class VoucherTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser('boss', 'b@example.com', 'pw')
        self.development = Development.objects.create(name='Estate')
        self.building, self.flats = make_project('Tower', floors=1, units=2, development=self.development)
        self.bank = make_account('Bank 1', opening_balance=100_000)
        self.category = CostCategory.objects.create(name='Civil', phase='POST')
        self.supplier = Supplier.objects.create(name='Steel Co')

    def voucher(self, amount=1000, **extra):
        """A cost as the form makes it: a voucher with nothing paid yet."""
        return ProjectCost.objects.create(project=self.building, cost_category=self.category, date=DAY, amount=amount, supplier=self.supplier, **extra)

    def pay(self, cost, amount, date=DAY):
        return CostPayment.objects.create(cost=cost, date=date, amount=amount, account=self.bank)


class VoucherTests(VoucherTestCase):
    def test_a_new_cost_is_an_unpaid_voucher(self):
        cost = self.voucher(1000)
        self.assertEqual((cost.paid_amount, cost.due_amount, cost.payment_status), (0, 1000, 'Unpaid'))
        self.assertRegex(cost.voucher_no, r'^CV-\d{5}$')

    def test_the_cost_form_has_no_account_the_money_is_paid_under_the_voucher(self):
        self.assertNotIn('account', SharedCostForm().fields)
        self.assertNotIn('account', DirectCostForm().fields)
        data = {'project': self.building.pk, 'cost_category': self.category.pk, 'date': DAY.isoformat(), 'amount': '700', 'supplier': self.supplier.pk}
        form = SharedCostForm(data=data)
        self.assertTrue(form.is_valid(), form.errors)
        cost = form.save()
        self.assertEqual((cost.account, cost.due_amount), (None, 700))
        self.assertEqual(collect_entries(development=self.development), [])          # nothing is in the book until it is paid

    def test_paying_in_parts(self):
        cost = self.voucher(1000)
        self.pay(cost, 300)
        self.assertEqual((cost.paid_amount, cost.due_amount, cost.payment_status), (300, 700, 'Part paid'))
        self.pay(cost, 700)
        self.assertEqual((cost.paid_amount, cost.due_amount, cost.payment_status), (1000, 0, 'Paid'))

    def test_an_older_cost_paid_in_full_when_recorded_counts_as_paid(self):
        old = self.voucher(500, account=self.bank)
        self.assertEqual((old.paid_amount, old.due_amount, old.payment_status), (500, 0, 'Paid'))

    def test_the_payment_form_takes_no_more_than_is_due(self):
        cost = self.voucher(1000)
        base = {'date': DAY.isoformat(), 'account': self.bank.pk}
        self.assertFalse(CostPaymentForm(data={**base, 'amount': '1001'}, cost=cost).is_valid())
        self.pay(cost, 400)
        too_much = CostPaymentForm(data={**base, 'amount': '601'}, cost=cost)
        self.assertFalse(too_much.is_valid())
        self.assertIn('amount', too_much.errors)
        self.assertTrue(CostPaymentForm(data={**base, 'amount': '600'}, cost=cost).is_valid())

    def test_a_voucher_paid_in_full_takes_no_more_payments(self):
        cost = self.voucher(1000)
        self.pay(cost, 1000)
        self.assertFalse(CostPaymentForm(data={'date': DAY.isoformat(), 'account': self.bank.pk, 'amount': '1'}, cost=cost).is_valid())

    def test_the_voucher_amount_cannot_drop_below_what_is_paid(self):
        cost = self.voucher(1000)
        self.pay(cost, 600)
        data = {'project': self.building.pk, 'cost_category': self.category.pk, 'date': DAY.isoformat(), 'amount': '500', 'supplier': self.supplier.pk}
        form = SharedCostForm(data=data, instance=cost)
        self.assertFalse(form.is_valid())
        self.assertIn('amount', form.errors)
        self.assertTrue(SharedCostForm(data={**data, 'amount': '800'}, instance=cost).is_valid())

    def test_payment_numbers(self):
        self.assertRegex(self.pay(self.voucher(), 10).payment_no, r'^CP-\d{5}$')


class BookTests(VoucherTestCase):
    def test_each_payment_is_a_line_in_the_book_waiting_to_be_verified(self):
        cost = self.voucher(1000)
        first, second = self.pay(cost, 300), self.pay(cost, 200)
        entries = {e.key: e for e in collect_entries(development=self.development)}
        self.assertEqual(set(entries), {f'cx:{first.pk}', f'cx:{second.pk}'})
        line = entries[f'cx:{first.pk}']
        self.assertEqual((line.source, line.money_out, line.money_in, line.confirmed, line.reference), ('Cost payment', 300, 0, False, first.payment_no))
        self.assertIn(cost.voucher_no, line.description)
        self.assertEqual(pending_count(), 2)
        self.assertEqual(pending_count(self.development), 2)

    def test_a_confirmed_payment_is_final_and_locks_the_voucher(self):
        cost = self.voucher(1000)
        payment = self.pay(cost, 300)
        done, problems = confirm_entries([f'cx:{payment.pk}'], self.user)
        self.assertEqual((done, problems), ([f'cx:{payment.pk}'], []))
        cost = ProjectCost.objects.get(pk=cost.pk)
        self.assertTrue(cost.is_confirmed)
        self.assertEqual(pending_count(), 0)

    def test_a_payment_that_would_overdraw_the_account_is_refused(self):
        cost = self.voucher(500_000)
        payment = self.pay(cost, 200_000)                   # the account holds 100,000
        done, problems = confirm_entries([f'cx:{payment.pk}'], self.user)
        self.assertEqual(done, [])
        self.assertIn('below zero', problems[0])

    def test_an_older_whole_cost_line_is_still_collected(self):
        old = self.voucher(500, account=self.bank)
        self.assertEqual([e.key for e in collect_entries(development=self.development)], [f'pc:{old.pk}'])


class ScreenTests(VoucherTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.user)
        unlock_client(self.client)
        enter_project(self.client, self.development)
        self.cost = self.voucher(1000)

    def test_the_pay_page_shows_the_voucher_and_what_is_due(self):
        page = self.client.get(reverse('costing:cost-pay', args=[self.cost.pk])).content.decode()
        for text in (self.cost.voucher_no, 'Steel Co', '1,000.00', 'Still due'):
            self.assertIn(text, page, text)

    def test_paying_through_the_page(self):
        response = self.client.post(reverse('costing:cost-pay', args=[self.cost.pk]), {
            'date': DAY.isoformat(), 'amount': '250', 'account': self.bank.pk, 'reference_no': 'CHQ-9', 'notes': '',
        })
        self.assertRedirects(response, reverse('costing:voucher-payments'))
        payment = self.cost.payments.get()
        self.assertEqual((payment.amount, payment.reference_no), (250, 'CHQ-9'))
        self.assertEqual(ProjectCost.objects.get(pk=self.cost.pk).due_amount, 750)

    def test_more_than_the_due_is_refused_on_the_page(self):
        response = self.client.post(reverse('costing:cost-pay', args=[self.cost.pk]), {'date': DAY.isoformat(), 'amount': '2000', 'account': self.bank.pk})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(CostPayment.objects.exists())

    def test_a_paid_voucher_sends_you_back_to_it(self):
        self.pay(self.cost, 1000)
        self.assertRedirects(self.client.get(reverse('costing:cost-pay', args=[self.cost.pk])), reverse('costing:voucher-payments'))

    def test_the_voucher_page_lists_its_payments_and_what_is_due(self):
        payment = self.pay(self.cost, 300)
        page = self.client.get(self.cost.get_absolute_url()).content.decode()
        for text in (payment.payment_no, 'Payments under this voucher', 'Part paid', '700.00'):
            self.assertIn(text, page, text)

    def test_the_printed_voucher_lists_the_payments(self):
        payment = self.pay(self.cost, 300)
        page = self.client.get(reverse('costing:cost-voucher', args=[self.cost.pk])).content.decode()
        for text in (payment.payment_no, 'Payments made under this voucher', 'Balance due', '700.00'):
            self.assertIn(text, page, text)

    def test_the_cost_list_shows_what_is_due_but_pays_nothing(self):
        page = self.client.get(reverse('costing:cost-list')).content.decode()
        self.assertIn(self.cost.voucher_no, page)
        self.assertNotIn(reverse('costing:cost-pay', args=[self.cost.pk]), page)

    def test_a_voucher_is_paid_from_the_voucher_payments_page_only(self):
        pay = reverse('costing:cost-pay', args=[self.cost.pk])
        page = self.client.get(reverse('costing:voucher-payments')).content.decode()
        self.assertIn(self.cost.voucher_no, page)
        self.assertIn(pay, page)
        for url in (reverse('costing:cost-list'), self.cost.get_absolute_url(), reverse('home')):
            self.assertNotIn(pay, self.client.get(url).content.decode(), url)
        self.assertIn('Voucher payments', self.client.get(self.cost.get_absolute_url()).content.decode())

    def test_the_voucher_payments_page_filters_and_lists_the_payments(self):
        paid = self.voucher(200)
        payment = self.pay(paid, 200)
        url = reverse('costing:voucher-payments')
        self.assertEqual([c.pk for c in self.client.get(url).context['rows']], [self.cost.pk])                  # still due is the default
        self.assertEqual([c.pk for c in self.client.get(url, {'show': 'paid'}).context['rows']], [paid.pk])
        self.assertEqual(len(self.client.get(url, {'show': 'all'}).context['rows']), 2)
        self.assertEqual(len(self.client.get(url, {'q': self.cost.voucher_no, 'show': 'all'}).context['rows']), 1)
        self.assertEqual(len(self.client.get(url, {'q': 'steel', 'show': 'all'}).context['rows']), 2)
        self.assertIn(payment.payment_no, self.client.get(url).content.decode())

    def test_the_voucher_payments_page_needs_a_project_and_is_in_the_menu(self):
        self.assertIn(reverse('costing:voucher-payments'), self.client.get(reverse('home')).content.decode())
        self.client.post(reverse('exit-project'))
        self.assertRedirects(self.client.get(reverse('costing:voucher-payments')), reverse('home'))

    def test_an_unconfirmed_payment_can_be_removed_a_confirmed_one_cannot(self):
        first, second = self.pay(self.cost, 300), self.pay(self.cost, 200)
        confirm_entries([f'cx:{second.pk}'], self.user)
        self.client.post(reverse('costing:payment-delete', args=[first.pk]))
        self.client.post(reverse('costing:payment-delete', args=[second.pk]))
        self.assertEqual(list(self.cost.payments.values_list('pk', flat=True)), [second.pk])

    def test_a_voucher_with_payments_cannot_be_deleted(self):
        self.pay(self.cost, 300)
        self.client.post(reverse('costing:cost-delete', args=[self.cost.pk]))
        self.assertTrue(ProjectCost.objects.filter(pk=self.cost.pk).exists())
        fresh = self.voucher(50)
        self.client.post(reverse('costing:cost-delete', args=[fresh.pk]))
        self.assertFalse(ProjectCost.objects.filter(pk=fresh.pk).exists())

    def test_a_voucher_with_a_confirmed_payment_cannot_be_edited(self):
        payment = self.pay(self.cost, 300)
        confirm_entries([f'cx:{payment.pk}'], self.user)
        response = self.client.get(reverse('costing:cost-update', args=[self.cost.pk]))
        self.assertRedirects(response, self.cost.get_absolute_url())

    def test_paying_needs_its_own_permission(self):
        clerk = User.objects.create_user('clerk', password='pw')
        clerk.user_permissions.add(Permission.objects.get(codename='view_projectcost'))
        self.client.force_login(clerk)
        unlock_client(self.client)
        enter_project(self.client, self.development)
        self.assertEqual(self.client.get(reverse('costing:cost-pay', args=[self.cost.pk])).status_code, 403)

    def test_another_projects_voucher_is_not_found(self):
        enter_project(self.client, Development.objects.create(name='Other'))
        self.assertEqual(self.client.get(reverse('costing:cost-pay', args=[self.cost.pk])).status_code, 404)

    def test_the_cost_form_page_no_longer_asks_for_an_account(self):
        page = self.client.get(reverse('costing:cost-create-shared')).content.decode()
        self.assertNotIn('id_account', page)


class ReportTests(VoucherTestCase):
    def test_the_daily_cost_report_shows_paid_and_due(self):
        cost = self.voucher(1000)
        self.pay(cost, 300)
        _, tables = daily_cost_report(None, self.development, DAY, DAY)
        totals = [t for t in tables if t.title == 'Totals'][0]
        self.assertEqual(totals.totals[2:5], [1000, 300, 700])
        row = [t for t in tables if t.title == 'Post-development costs'][0].rows[0]
        self.assertEqual(row[6:9], [1000, 300, 700])

    def test_the_supplier_ledger_counts_only_what_was_paid(self):
        cost = self.voucher(1000)
        self.pay(cost, 300)
        self.voucher(500, account=self.bank)                                # an older cost, paid in full
        client = self.client
        client.force_login(self.user)
        unlock_client(client)
        enter_project(client, self.development)
        response = client.get(reverse('suppliers:ledger', args=[self.supplier.pk]))
        self.assertEqual(response.context['closing_total'], 800)
        self.assertEqual(response.context['unpaid_total'], 700)
        self.assertIn('still due', response.content.decode())

    def test_the_finance_report_lists_unpaid_vouchers_as_payable(self):
        cost = self.voucher(1000)
        self.pay(cost, 300)
        _, tables = finance_report(None, self.development)
        costs = [t for t in tables if t.title == 'Cost and payable'][0]
        self.assertEqual(costs.rows[0][4], 700)                         # cost vouchers unpaid
        self.assertEqual(costs.rows[0][7], 700)                         # total payable

    def test_the_cash_position_counts_payments_made_not_vouchers_issued(self):
        cost = self.voucher(1000)
        self.pay(cost, 300)
        _, tables = profitability_report(None, self.development)
        cash = [t for t in tables if t.title.startswith('Cash position')][0].rows[0]
        self.assertEqual((cash[5], cash[6]), (300, -300))               # post-development cost paid, net cash

    def test_the_daily_transactions_report_has_the_payments(self):
        from reports.daily import day_book

        cost = self.voucher(1000)
        payment = self.pay(cost, 300)
        book = day_book(self.development, DAY, DAY)
        self.assertEqual([e.key for e in book['entries']], [f'cx:{payment.pk}'])


class HonorariumVoucherTests(VoucherTestCase):
    def test_every_booking_has_an_honorarium_voucher_and_the_payments_are_made_under_it(self):
        sale = FlatSale.objects.create(flat=self.flats[0], customer=Customer.objects.create(name='Rahim', phone='01711000001'), sale_date='2026-01-01', sale_value=1500)
        self.assertEqual(sale.honorarium_voucher_no, f'HV-{sale.pk:05d}')
        HonorariumPayment.objects.create(sale=sale, date=DAY, amount=100, account=self.bank)
        self.client.force_login(self.user)
        unlock_client(self.client)
        enter_project(self.client, self.development)
        listing = self.client.get(reverse('costing:honorarium-list')).content.decode()
        self.assertIn(sale.honorarium_voucher_no, listing)
        self.assertIn(sale.honorarium_voucher_no, self.client.get(reverse('sales:detail', args=[sale.pk])).content.decode())
        payment = HonorariumPayment.objects.get()
        self.assertIn(sale.honorarium_voucher_no, self.client.get(reverse('costing:honorarium-voucher', args=[payment.pk])).content.decode())


class MenuTests(VoucherTestCase):
    def test_each_module_menu_has_its_own_reports(self):
        self.client.force_login(self.user)
        unlock_client(self.client)
        enter_project(self.client, self.development)
        page = self.client.get(reverse('home')).content.decode()
        for name in ('reports:customer-wise', 'reports:customers', 'reports:dues', 'reports:flat-wise', 'reports:daily-costs', 'reports:collection',
                     'reports:profit-loss', 'reports:daily'):
            self.assertGreaterEqual(page.count(reverse(name)), 2, name)        # in its module's menu and in the Reports menu
        self.assertIn('Customer reports', self.client.get(reverse('customers:list')).content.decode())
