"""The customer-wise report: customers who booked a flat in the project, with their bookings, payments, cost and installments."""
import datetime
from decimal import Decimal
from io import BytesIO

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from openpyxl import load_workbook

from core.testing import enter_project, make_account, make_project, unlock_client
from costing.models import CostCategory, ProjectCost
from customers.models import Customer
from installments import services as installments
from projects.models import Development
from sales.models import CustomerPayment, FlatSale

from .customer_wise import customer_wise_report

D = Decimal
TODAY = datetime.date.today()
LATER = TODAY + datetime.timedelta(days=20)


class CustomerWiseTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser('boss', 'b@example.com', 'pw')
        self.development = Development.objects.create(name='Estate')
        # base 1000, parking 100, quoted 1200
        self.building, self.flats = make_project('Tower', floors=1, units=4, development=self.development)
        self.bank = make_account('Bank 1')
        self.rahim = Customer.objects.create(name='Rahim', phone='01711000001')
        self.karim = Customer.objects.create(name='Karim', phone='01711000002')
        self.nobody = Customer.objects.create(name='Never Booked', phone='01711000003')
        self.cancelled_buyer = Customer.objects.create(name='Gone', phone='01711000004')
        # Rahim books two flats, one with parking; Karim one
        self.rahim_a = FlatSale.objects.create(
            flat=self.flats[0], customer=self.rahim, sale_date='2026-01-01', with_parking=True, sale_value=1800, parking_sale_value=250, reg_value=50)
        self.rahim_b = FlatSale.objects.create(flat=self.flats[1], customer=self.rahim, sale_date='2026-01-05', sale_value=1500)
        self.karim_sale = FlatSale.objects.create(flat=self.flats[2], customer=self.karim, sale_date='2026-01-09', sale_value=1300)
        self.gone = FlatSale.objects.create(flat=self.flats[3], customer=self.cancelled_buyer, sale_date='2026-01-10', sale_value=1200)
        CustomerPayment.objects.create(sale=self.gone, payment_date='2026-02-01', amount=400, account=self.bank)
        self.gone.cancel(50)
        self.gone.save()
        CustomerPayment.objects.create(sale=self.rahim_a, payment_date='2026-02-01', amount=600, account=self.bank)
        self.category = CostCategory.objects.create(name='Civil', phase='POST')
        ProjectCost.objects.create(project=self.building, cost_category=self.category, date='2026-02-02', amount=400, account=self.bank, paid_to='Vendor')

    def table(self, title, development=None, project=None):
        _, tables = customer_wise_report(project, development or self.development)
        return [t for t in tables if t.title == title][0]


class ReportContentTests(CustomerWiseTestCase):
    def summary(self):
        return {row[1]: row for row in self.table('Customer summary').rows}

    def test_only_customers_who_booked_a_flat_are_listed(self):
        self.assertEqual(set(self.summary()), {'Rahim', 'Karim'})       # not the customer with no booking, not the cancelled one

    def test_the_customer_summary_adds_up_each_customers_flats(self):
        rahim = self.summary()['Rahim']
        # id, name, phone, flats, flat nos, sale value, net value, received, receivable, cost, charged, due, overdue
        self.assertEqual((rahim[0], rahim[3], rahim[4]), (self.rahim.customer_code, 2, f'{self.flats[0].flat_no}, {self.flats[1].flat_no}'))
        self.assertEqual((rahim[5], rahim[6], rahim[7], rahim[8]), (3300, 3350, 600, 2750))

    def test_each_customers_share_of_the_post_development_cost(self):
        # 400 shared over 4 flats = 100 per flat; Rahim holds two flats
        self.assertEqual(self.summary()['Rahim'][9], 200)
        self.assertEqual(self.summary()['Karim'][9], 100)

    def test_the_totals_row(self):
        totals = self.table('Customer summary').totals
        self.assertEqual((totals[0], totals[3], totals[5], totals[6], totals[7], totals[8]), ('Total', 3, 4600, 4650, 600, 4050))

    def test_flat_booking_details(self):
        rows = {r[1]: r for r in self.table('Flat booking details').rows}
        self.assertEqual(len(rows), 3)
        row = rows[self.rahim_a.sale_no]
        self.assertEqual(row[0], 'Rahim')
        self.assertEqual((row[2], row[4], row[5]), (datetime.date(2026, 1, 1), self.flats[0].flat_no, self.flats[0].floor_no))
        self.assertEqual((row[6], row[9]), (self.flats[0].get_flat_type_display(), 'Booked'))
        self.assertEqual(row[8], self.flats[0].parking_lot)             # parking taken: its lot is shown
        self.assertEqual(rows[self.rahim_b.sale_no][8], 'Not taken')

    def test_a_registered_booking_shows_its_registry_date(self):
        self.karim_sale.register(datetime.date(2026, 3, 1))
        self.karim_sale.save()
        row = [r for r in self.table('Flat booking details').rows if r[1] == self.karim_sale.sale_no][0]
        self.assertEqual((row[9], row[10]), ('Registered', datetime.date(2026, 3, 1)))

    def test_sales_payments_and_cost_by_booking_with_the_flat_and_parking_values_apart(self):
        row = [r for r in self.table('Sales, payments and cost by booking').rows if r[1] == self.flats[0].flat_no][0]
        # customer, flat, flat sale, parking sale, sale value, reg, net, received, receivable, cost, credit
        self.assertEqual(row[2:10], [1550, 250, 1800, 50, 1850, 600, 1250, 100])

    def test_installments_with_deadline_paid_and_due(self):
        installments.issue(self.development, self.user, 'Installment 1', LATER, 'FIXED', D(500))
        CustomerPayment.objects.create(sale=self.karim_sale, payment_date=TODAY, amount=200, account=self.bank,
                                       invoice=self.karim_sale.invoices.get(kind='INSTALLMENT'))
        rows = {(r[0], r[1]): r for r in self.table('Installments by booking').rows}
        karim = rows[('Karim', self.flats[2].flat_no)]
        self.assertEqual((karim[2], karim[3], karim[4], karim[5], karim[6], karim[7]), ('Installment 1', LATER, 500, 200, 300, 'Partly paid'))
        summary = self.summary()
        self.assertEqual((summary['Rahim'][10], summary['Rahim'][11], summary['Karim'][11]), (1000, 1000, 300))

    def test_overdue_installments_are_counted_apart(self):
        installments.issue(self.development, self.user, 'Old', TODAY - datetime.timedelta(days=2), 'FIXED', D(400))
        self.assertEqual(self.summary()['Karim'][12], 400)

    def test_cancelled_bookings_have_a_table_of_their_own(self):
        table = self.table('Cancelled bookings (not in the tables above)')
        self.assertEqual(len(table.rows), 1)
        row = table.rows[0]
        self.assertEqual((row[0], row[4], row[5], row[6], row[8]), ('Gone', 400, 50, 200, 200))     # refund 50% of 400, none paid yet

    def test_without_cancellations_there_is_no_such_table(self):
        self.gone.delete()
        _, tables = customer_wise_report(None, self.development)
        self.assertNotIn('Cancelled bookings (not in the tables above)', [t.title for t in tables])

    def test_other_projects_and_buildings_are_left_out(self):
        other = Development.objects.create(name='Other')
        far, flats = make_project('Villa', floors=1, units=1, development=other)
        FlatSale.objects.create(flat=flats[0], customer=self.nobody, sale_date='2026-01-01', sale_value=2000)
        self.assertNotIn('Never Booked', self.summary())
        second, second_flats = make_project('Annex', floors=1, units=1, development=self.development)
        FlatSale.objects.create(flat=second_flats[0], customer=self.nobody, sale_date='2026-01-01', sale_value=2000)
        self.assertIn('Never Booked', self.summary())
        only = {r[1] for r in self.table('Customer summary', project=self.building, development=None).rows}
        self.assertNotIn('Never Booked', only)

    def test_a_project_with_no_bookings_gives_empty_tables(self):
        empty = Development.objects.create(name='Empty')
        make_project('Shell', floors=1, units=1, development=empty)
        table = self.table('Customer summary', development=empty)
        self.assertEqual((table.rows, table.totals), ([], None))


class ReportScreenTests(CustomerWiseTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.user)
        unlock_client(self.client)
        enter_project(self.client, self.development)

    def test_the_page_shows_the_tables(self):
        page = self.client.get(reverse('reports:customer-wise')).content.decode()
        for text in ('Customer-wise Report', 'Customer summary', 'Flat booking details', 'Installments by booking',
                     'Rahim', 'Karim', self.rahim.customer_code):
            self.assertIn(text, page, text)
        self.assertNotIn('Never Booked', page)

    def test_pdf_and_excel(self):
        pdf = self.client.get(reverse('reports:customer-wise'), {'format': 'pdf'})
        self.assertTrue(pdf.content.startswith(b'%PDF'))
        xlsx = self.client.get(reverse('reports:customer-wise'), {'format': 'xlsx'})
        cells = {str(c.value) for row in load_workbook(BytesIO(xlsx.content)).active.iter_rows() for c in row}
        self.assertIn('Rahim', cells)
        self.assertIn(self.rahim_a.sale_no, cells)

    def test_it_is_always_about_the_open_project(self):
        other = Development.objects.create(name='Other')
        far, flats = make_project('Villa', floors=1, units=1, development=other)
        FlatSale.objects.create(flat=flats[0], customer=self.nobody, sale_date='2026-01-01', sale_value=2000)
        page = self.client.get(reverse('reports:customer-wise'), {'development': other.pk}).content.decode()
        self.assertNotIn('Never Booked', page)

    def test_it_needs_a_project(self):
        self.client.post(reverse('exit-project'))
        self.assertRedirects(self.client.get(reverse('reports:customer-wise')), reverse('home'))

    def test_it_is_in_the_menu_and_the_report_centre(self):
        for url in (reverse('home'), reverse('reports:index')):
            self.assertIn(reverse('reports:customer-wise'), self.client.get(url).content.decode())
