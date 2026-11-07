"""The honorarium payment detail: every sale's honorarium, what was paid to the ref, what is still due."""
from decimal import Decimal
from io import BytesIO

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from openpyxl import load_workbook

from core.testing import enter_project, make_account, make_project, unlock_client
from customers.models import Customer
from projects.models import Development

from .models import FlatSale, HonorariumPayment, Reference

D = Decimal


class HonorariumTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser('boss', 'b@example.com', 'pw')
        self.development = Development.objects.create(name='Estate')
        # base 1000, parking 100, quoted 1200
        self.building, self.flats = make_project('Tower', floors=1, units=4, development=self.development)
        self.bank = make_account('Bank 1')
        self.rahim = Reference.objects.create(name='Rahim Ref', phone='01711000001')
        self.karim = Reference.objects.create(name='Karim Ref')
        self.buyer = Customer.objects.create(name='Buyer One', phone='01711000009')
        # honorarium 500 (sale 1500 - base 1000), partly paid
        self.sale = self.make_sale(self.flats[0], 1500, self.rahim)
        self.first = self.pay(self.sale, 200, '2026-02-01')
        self.second = self.pay(self.sale, 100, '2026-03-01')
        # honorarium 300, nothing paid yet
        self.unpaid = self.make_sale(self.flats[1], 1300, self.karim)
        # no honorarium at all (sold at the base price)
        self.plain = self.make_sale(self.flats[2], 1000, None)

    def make_sale(self, flat, value, ref):
        return FlatSale.objects.create(flat=flat, customer=self.buyer, sale_date='2026-01-01', sale_value=value, ref=ref)

    def pay(self, sale, amount, date):
        return HonorariumPayment.objects.create(sale=sale, date=date, amount=amount, account=self.bank, notes=f'part {amount}')


class HonorariumListTests(HonorariumTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.user)
        unlock_client(self.client)
        enter_project(self.client, self.development)

    def get(self, **query):
        response = self.client.get(reverse('costing:honorarium-list'), query)
        self.assertEqual(response.status_code, 200)
        return response

    def sales_in(self, response):
        return [r['sale'] for r in response.context['rows']]

    def test_every_sale_with_an_honorarium_is_listed_with_paid_and_due(self):
        response = self.get()
        rows = {r['sale'].pk: r for r in response.context['rows']}
        self.assertEqual(set(rows), {self.sale.pk, self.unpaid.pk})            # the sale with no honorarium is left out
        self.assertEqual((rows[self.sale.pk]['honorarium'], rows[self.sale.pk]['paid'], rows[self.sale.pk]['due']), (500, 300, 200))
        self.assertEqual((rows[self.unpaid.pk]['honorarium'], rows[self.unpaid.pk]['paid'], rows[self.unpaid.pk]['due']), (300, 0, 300))

    def test_totals(self):
        context = self.get().context
        self.assertEqual((context['total_honorarium'], context['total_paid'], context['total_due']), (800, 300, 500))
        self.assertEqual(context['payment_count'], 2)

    def test_the_payments_are_shown_with_voucher_numbers_and_accounts(self):
        page = self.get().content.decode()
        for text in (self.first.reference_no, self.second.reference_no, 'Bank 1', 'part 200', 'Rahim Ref', 'Karim Ref'):
            self.assertIn(text, page, text)
        self.assertIn(reverse('costing:honorarium-voucher', args=[self.first.pk]), page)

    def test_filter_by_ref(self):
        rows = self.sales_in(self.get(ref=self.karim.pk))
        self.assertEqual(rows, [self.unpaid])

    def test_only_what_is_still_due(self):
        self.pay(self.unpaid, 300, '2026-03-05')
        rows = self.sales_in(self.get(only_due='1'))
        self.assertEqual(rows, [self.sale])

    def test_filter_by_payment_date_shows_only_those_payments_and_sales(self):
        response = self.get(date_from='2026-02-15', date_to='2026-03-31')
        self.assertEqual(self.sales_in(response), [self.sale])
        row = response.context['rows'][0]
        self.assertEqual([p.pk for p in row['payments']], [self.second.pk])
        self.assertEqual(row['paid'], 100)
        self.assertEqual(row['due'], 200)             # the due amount is still today's, not the period's

    def test_a_cancelled_sale_keeps_its_payments_but_owes_nothing(self):
        self.sale.cancel(100)
        self.sale.save()
        row = [r for r in self.get().context['rows'] if r['sale'].pk == self.sale.pk][0]
        self.assertEqual((row['paid'], row['due']), (300, 0))

    def test_other_projects_are_not_listed(self):
        other = Development.objects.create(name='Other')
        building, flats = make_project('Villa', floors=1, units=1, development=other)
        far = FlatSale.objects.create(flat=flats[0], customer=self.buyer, sale_date='2026-01-01', sale_value=2000, ref=self.rahim)
        self.assertNotIn(far, self.sales_in(self.get()))

    def test_it_needs_a_project_to_be_open(self):
        client = self.client.__class__()
        client.force_login(self.user)
        unlock_client(client)
        self.assertRedirects(client.get(reverse('costing:honorarium-list')), reverse('home'))

    def test_it_asks_for_the_password_while_the_screens_are_locked(self):
        client = self.client.__class__()
        client.force_login(self.user)
        enter_project(client, self.development)
        response = client.get(reverse('costing:honorarium-list'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('/confirm-password/', response['Location'])

    def test_it_lives_in_the_costing_menu_not_the_sales_menu(self):
        page = self.client.get(reverse('home')).content.decode()
        costing_menu = page[page.index('fa-coins'):page.index('fa-dollar-sign')]
        sales_menu = page[page.index('fa-dollar-sign'):page.index('fa-user-tie')]
        self.assertIn(reverse('costing:honorarium-list'), costing_menu)
        self.assertNotIn(reverse('costing:honorarium-list'), sales_menu)

    def test_it_is_paid_from_here_not_from_the_sale_page(self):
        pay = reverse('costing:honorarium-pay', args=[self.sale.pk])
        self.assertIn(pay, self.client.get(reverse('costing:honorarium-list')).content.decode())
        self.assertNotIn(pay, self.client.get(reverse('sales:detail', args=[self.sale.pk])).content.decode())
        response = self.client.post(pay, {'date': '2026-04-01', 'amount': '50', 'account': self.bank.pk, 'notes': ''})
        self.assertRedirects(response, reverse('costing:honorarium-list'))
        self.assertEqual(HonorariumPayment.objects.filter(sale=self.sale).count(), 3)

    def test_the_menu_links_to_it(self):
        self.assertIn(reverse('costing:honorarium-list'), self.client.get(reverse('home')).content.decode())

    def test_the_sale_page_links_each_payment_to_its_voucher(self):
        page = self.client.get(reverse('sales:detail', args=[self.sale.pk])).content.decode()
        self.assertIn(reverse('costing:honorarium-voucher', args=[self.first.pk]), page)


class HonorariumExcelTests(HonorariumTestCase):
    def test_the_excel_file_has_the_sales_and_the_payments(self):
        self.client.force_login(self.user)
        unlock_client(self.client)
        enter_project(self.client, self.development)
        response = self.client.get(reverse('costing:honorarium-list'), {'format': 'xlsx'})
        self.assertEqual(response.status_code, 200)
        workbook = load_workbook(BytesIO(response.content))
        cells = {str(c.value) for sheet in workbook for row in sheet.iter_rows() for c in row}
        for text in (self.sale.sale_no, self.unpaid.sale_no, self.first.reference_no, 'Rahim Ref', 'Bank 1', 'part 100'):
            self.assertIn(text, cells, text)
        self.assertNotIn(self.plain.sale_no, cells)


class HonorariumVoucherTests(HonorariumTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.user)
        unlock_client(self.client)
        enter_project(self.client, self.development)

    def test_the_voucher_shows_the_position_as_of_that_payment(self):
        page = self.client.get(reverse('costing:honorarium-voucher', args=[self.first.pk])).content.decode()
        self.assertIn('HONORARIUM PAYMENT VOUCHER', page)
        self.assertIn(self.first.reference_no, page)
        self.assertIn('Rahim Ref', page)
        context = self.client.get(reverse('costing:honorarium-voucher', args=[self.first.pk])).context
        self.assertEqual((context['paid_to_date'], context['balance_after']), (200, 300))     # not today's 300 / 200
        later = self.client.get(reverse('costing:honorarium-voucher', args=[self.second.pk])).context
        self.assertEqual((later['paid_to_date'], later['balance_after']), (300, 200))

    def test_another_projects_voucher_is_not_found(self):
        enter_project(self.client, Development.objects.create(name='Other'))
        self.assertEqual(self.client.get(reverse('costing:honorarium-voucher', args=[self.first.pk])).status_code, 404)
