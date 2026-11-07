"""Daily transactions (check and verify), profitability analysis, invoice PDF and the automatic daily reports."""
import datetime
import tempfile
from decimal import Decimal
from io import BytesIO
from pathlib import Path

from django.contrib.auth.models import User
from django.core import mail
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.urls import reverse
from openpyxl import load_workbook

from books.models import Account
from costing.models import CostCategory, ProjectCost
from core.testing import enter_project, make_account, make_project, unlock_client
from customers.models import Customer
from directors.models import Director, DirectorTransaction
from projects.models import Development
from sales.models import CustomerPayment, FlatSale, HonorariumPayment

from .daily import PENDING, VERIFIED, day_book
from .profitability import profitability_report

D = Decimal
DAY = datetime.date(2026, 3, 10)


class DayTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser('boss', 'b@example.com', 'pw')
        self.development = Development.objects.create(name='Estate')
        # base 1000, parking 100, quoted 1200
        self.building, self.flats = make_project('Tower', floors=1, units=4, development=self.development)
        self.bank = make_account('Bank 1', opening_balance=5000)
        self.customer = Customer.objects.create(name='Rahim', phone='01711000001')
        self.sale = FlatSale.objects.create(flat=self.flats[0], customer=self.customer, sale_date='2026-01-01', sale_value=1500)
        self.category = CostCategory.objects.create(name='Civil', phase='POST')
        self.payment = CustomerPayment.objects.create(sale=self.sale, payment_date=DAY, amount=400, account=self.bank)
        self.cost = ProjectCost.objects.create(project=self.building, cost_category=self.category, date=DAY, amount=150, account=self.bank)
        self.other_day = CustomerPayment.objects.create(sale=self.sale, payment_date=DAY + datetime.timedelta(days=1), amount=70, account=self.bank)

    def login(self, unlocked=True):
        self.client.force_login(self.user)
        if unlocked:
            unlock_client(self.client)
        enter_project(self.client, self.development)


class DayBookTests(DayTestCase):
    def test_only_the_days_transactions_are_in_it(self):
        book = day_book(self.development, DAY, DAY)
        self.assertEqual({e.key for e in book['entries']}, {f'cp:{self.payment.pk}', f'pc:{self.cost.pk}'})
        self.assertEqual((book['money_in'], book['money_out']), (400, 150))

    def test_a_period_covers_several_days(self):
        book = day_book(self.development, DAY, DAY + datetime.timedelta(days=1))
        self.assertEqual(len(book['entries']), 3)

    def test_each_entry_is_verified_or_not(self):
        self.payment.confirm(self.user)
        book = day_book(self.development, DAY, DAY)
        status = {e.key: e.status for e in book['entries']}
        self.assertEqual(status[f'cp:{self.payment.pk}'], VERIFIED)
        self.assertEqual(status[f'pc:{self.cost.pk}'], PENDING)
        self.assertEqual((book['verified'], book['pending']), (1, 1))

    def test_a_verified_entry_says_who_verified_it_and_when(self):
        self.payment.confirm(self.user)
        entry = [e for e in day_book(self.development, DAY, DAY)['entries'] if e.key.startswith('cp:')][0]
        self.assertEqual(entry.verified_by, 'boss')
        self.assertIsNotNone(entry.verified_at)

    def test_an_entry_with_no_account_is_listed_and_cannot_be_verified_yet(self):
        old = CustomerPayment.objects.create(sale=self.sale, payment_date=DAY, amount=33, account=None)
        entry = [e for e in day_book(self.development, DAY, DAY)['entries'] if e.key == f'cp:{old.pk}'][0]
        self.assertEqual(entry.status, 'No account yet')

    def test_other_projects_are_left_out(self):
        other = Development.objects.create(name='Other')
        building, flats = make_project('Villa', floors=1, units=1, development=other)
        sale = FlatSale.objects.create(flat=flats[0], customer=self.customer, sale_date='2026-01-01', sale_value=1500)
        CustomerPayment.objects.create(sale=sale, payment_date=DAY, amount=999, account=self.bank)
        self.assertEqual(day_book(self.development, DAY, DAY)['money_in'], 400)

    def test_every_kind_of_transaction_is_included(self):
        HonorariumPayment.objects.create(sale=self.sale, date=DAY, amount=20, account=self.bank)
        director = Director.objects.create(name='Karim')
        DirectorTransaction.objects.create(director=director, development=self.development, kind='INVESTMENT', date=DAY, amount=900, account=self.bank)
        sources = set(day_book(self.development, DAY, DAY)['by_source'])
        self.assertEqual(sources, {'Payment received', 'Cost payment', 'Honorarium paid', 'Director investment'})


class DailyScreenTests(DayTestCase):
    def get(self, **query):
        response = self.client.get(reverse('reports:daily'), {'date_from': DAY.isoformat(), 'date_to': DAY.isoformat(), **query})
        self.assertEqual(response.status_code, 200)
        return response

    def test_the_screen_lists_the_day(self):
        self.login()
        page = self.get().content.decode()
        self.assertIn('Daily transactions', page)
        self.assertIn(self.payment.sale.sale_no.split('/')[0], page)
        self.assertIn('Not verified', page)
        self.assertNotIn(f'value="pc:{self.other_day.pk}"', page)

    def test_verifying_from_the_screen_puts_the_entries_in_the_book(self):
        self.login()
        page = self.get().content.decode()
        self.assertIn(f'value="cp:{self.payment.pk}"', page)
        self.client.post(reverse('books:confirm'), {'entries': [f'cp:{self.payment.pk}'], 'next': f'{reverse("reports:daily")}?date_from={DAY}'})
        self.payment.refresh_from_db()
        self.assertTrue(self.payment.is_confirmed)
        self.assertIn('Verified', self.get().content.decode())

    def test_without_the_permission_there_is_nothing_to_tick(self):
        clerk = User.objects.create_user('clerk', password='pw')
        from django.contrib.auth.models import Permission
        clerk.user_permissions.add(Permission.objects.get(codename='view_customerpayment'))
        self.client.force_login(clerk)
        unlock_client(self.client)
        enter_project(self.client, self.development)
        page = self.get().content.decode()
        self.assertNotIn('class="verify-box', page)

    def test_the_day_can_be_downloaded_as_pdf_and_excel(self):
        self.login()
        pdf = self.get(format='pdf')
        self.assertEqual(pdf['Content-Type'], 'application/pdf')
        self.assertTrue(pdf.content.startswith(b'%PDF'))
        xlsx = self.get(format='xlsx')
        cells = {str(c.value) for row in load_workbook(BytesIO(xlsx.content)).active.iter_rows() for c in row}
        self.assertIn('Payment received', cells)
        self.assertIn('Pending', cells)

    def test_it_needs_a_project(self):
        self.client.force_login(self.user)
        unlock_client(self.client)
        self.assertRedirects(self.client.get(reverse('reports:daily')), reverse('home'))

    def test_it_asks_for_the_password_while_the_screens_are_locked(self):
        self.login(unlocked=False)
        response = self.client.get(reverse('reports:daily'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('/confirm-password/', response['Location'])

    def test_it_opens_on_today_when_no_date_is_given(self):
        self.login()
        response = self.client.get(reverse('reports:daily'))
        self.assertEqual(response.context['date_from'], datetime.date.today())

    def test_a_reversed_range_is_put_right(self):
        self.login()
        response = self.client.get(reverse('reports:daily'), {'date_from': '2026-03-12', 'date_to': '2026-03-10'})
        self.assertEqual((response.context['date_from'], response.context['date_to']), (DAY, datetime.date(2026, 3, 12)))


class ProfitabilityTests(DayTestCase):
    def rows(self, tables, title):
        return [t for t in tables if t.title == title][0].rows

    def test_profit_is_base_price_earned_less_pre_development_cost(self):
        pre = CostCategory.objects.create(name='Land', phase='PRE')
        ProjectCost.objects.create(project=self.building, cost_category=pre, date=DAY, amount=300, account=self.bank)
        _, tables = profitability_report(None, self.development)
        row = self.rows(tables, 'Profitability by building')[0]
        # 1 sale at 1500: honorarium 500, earned 1000; pre-development cost 300; post cost 150 is the owners' cost
        self.assertEqual((row[1], row[2], row[3], row[4], row[6], row[7]), (1, 1500, 500, 1000, 300, 700))
        self.assertAlmostEqual(float(row[8]), 70.0)       # 700 / 1000
        self.assertAlmostEqual(float(row[9]), 233.33, places=1)

    def test_what_the_unsold_flats_would_add(self):
        _, tables = profitability_report(None, self.development)
        row = self.rows(tables, 'Profitability by building')[0]
        self.assertEqual((row[10], row[11], row[12]), (3, 3000, row[7] + 3000))      # 3 unsold flats at base price 1000

    def test_cancelled_sales_keep_what_the_company_held_back(self):
        second = FlatSale.objects.create(flat=self.flats[1], customer=self.customer, sale_date='2026-01-02', sale_value=1300)
        CustomerPayment.objects.create(sale=second, payment_date=DAY, amount=600, account=self.bank)
        second.cancel(50)
        second.save()
        _, tables = profitability_report(None, self.development)
        row = self.rows(tables, 'Profitability by building')[0]
        self.assertEqual(row[5], 300)         # received 600, refundable 50%

    def test_cash_position(self):
        HonorariumPayment.objects.create(sale=self.sale, date=DAY, amount=100, account=self.bank)
        _, tables = profitability_report(None, self.development)
        row = self.rows(tables, 'Cash position (money actually moved)')[0]
        # received 400 + 70, honorarium paid 100, post cost 150
        self.assertEqual((row[1], row[3], row[5], row[6]), (470, 100, 150, 220))

    def test_cost_by_head_shows_each_heads_share(self):
        _, tables = profitability_report(None, self.development)
        heads = self.rows(tables, 'Cost by head')
        self.assertEqual((heads[0][0], heads[0][2], heads[0][3]), ('Civil', 150, 100))

    def test_the_report_page_pdf_and_excel_open(self):
        self.login()
        for query in ({}, {'format': 'pdf'}, {'format': 'xlsx'}):
            self.assertEqual(self.client.get(reverse('reports:profitability'), query).status_code, 200)

    def test_it_is_in_the_menu_and_report_centre(self):
        self.login()
        for url in (reverse('home'), reverse('reports:index')):
            page = self.client.get(url).content.decode()
            self.assertIn(reverse('reports:profitability'), page)
            self.assertIn(reverse('reports:daily'), page)


class InvoicePdfTests(DayTestCase):
    def test_the_invoice_is_available_as_a_pdf(self):
        self.login()
        response = self.client.get(reverse('sales:invoice', args=[self.sale.pk]), {'format': 'pdf'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertTrue(response.content.startswith(b'%PDF'))
        self.assertIn('invoice_', response['Content-Disposition'])
        self.assertNotIn('/', response['Content-Disposition'].split('filename=')[1].strip('"'))

    def test_a_sale_with_parking_and_registration_cost_makes_a_pdf_too(self):
        sale = FlatSale.objects.create(
            flat=self.flats[1], customer=self.customer, sale_date='2026-01-02', with_parking=True, sale_value=1700, reg_value=60,
        )
        CustomerPayment.objects.create(sale=sale, payment_date=DAY, amount=2000, account=self.bank)    # more than the net value
        self.login()
        response = self.client.get(reverse('sales:invoice', args=[sale.pk]), {'format': 'pdf'})
        self.assertTrue(response.content.startswith(b'%PDF'))

    def test_the_html_invoice_has_a_pdf_button(self):
        self.login()
        page = self.client.get(reverse('sales:invoice', args=[self.sale.pk])).content.decode()
        self.assertIn('?format=pdf', page)
        detail = self.client.get(reverse('sales:detail', args=[self.sale.pk])).content.decode()
        self.assertIn('Statement PDF', detail)

    def test_the_private_link_gives_a_pdf_without_logging_in(self):
        from sms.whatsapp import invoice_url

        self.login()
        link = invoice_url(self.client.get('/').wsgi_request, self.sale)
        self.client.logout()
        response = self.client.get(link, {'format': 'pdf'})
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertEqual(response['Cache-Control'], 'private, no-store')

    def test_another_projects_invoice_is_not_found(self):
        self.login()
        enter_project(self.client, Development.objects.create(name='Other'))
        self.assertEqual(self.client.get(reverse('sales:invoice', args=[self.sale.pk]), {'format': 'pdf'}).status_code, 404)


class AutomaticReportTests(DayTestCase):
    def run_command(self, *args, **kwargs):
        with tempfile.TemporaryDirectory() as folder:
            with override_settings(REPORTS_DIR=folder):
                call_command('generate_daily_reports', *args, verbosity=0, **kwargs)
            return sorted(str(p.relative_to(folder)).replace('\\', '/') for p in Path(folder).rglob('*') if p.is_file())

    def test_it_writes_the_days_pdf_excel_and_the_profitability_analysis(self):
        files = self.run_command('--date', DAY.isoformat())
        code = self.development.code
        self.assertEqual(files, [
            f'{code}/2026-03-10/daily_costs_{code}_2026-03-10.pdf',
            f'{code}/2026-03-10/daily_transactions_{code}_2026-03-10.pdf',
            f'{code}/2026-03-10/daily_transactions_{code}_2026-03-10.xlsx',
            f'{code}/2026-03-10/profitability_{code}_2026-03-10.pdf',
        ])

    def test_the_files_are_real_reports(self):
        with tempfile.TemporaryDirectory() as folder:
            call_command('generate_daily_reports', '--date', DAY.isoformat(), '--output', folder, verbosity=0)
            code = self.development.code
            base = Path(folder) / code / '2026-03-10'
            self.assertTrue((base / f'daily_transactions_{code}_2026-03-10.pdf').read_bytes().startswith(b'%PDF'))
            cells = {str(c.value) for row in load_workbook(base / f'daily_transactions_{code}_2026-03-10.xlsx').active.iter_rows() for c in row}
            self.assertIn('Payment received', cells)

    def test_a_day_with_nothing_writes_nothing_unless_asked(self):
        quiet = (DAY + datetime.timedelta(days=30)).isoformat()
        self.assertEqual(self.run_command('--date', quiet), [])
        self.assertEqual(len(self.run_command('--date', quiet, '--include-empty')), 4)

    def test_profitability_can_be_skipped(self):
        files = self.run_command('--date', DAY.isoformat(), '--skip-profitability')
        self.assertEqual(len(files), 3)

    def test_one_project_only(self):
        other = Development.objects.create(name='Other')
        make_project('Villa', floors=1, units=1, development=other)
        files = self.run_command('--date', DAY.isoformat(), '--project', self.development.code)
        self.assertTrue(all(f.startswith(self.development.code) for f in files))
        with self.assertRaises(CommandError):
            self.run_command('--project', 'NOPE')

    def test_a_bad_date_is_refused(self):
        with self.assertRaises(CommandError):
            self.run_command('--date', 'yesterday-ish')

    def test_it_e_mails_the_files_to_the_recipients(self):
        with tempfile.TemporaryDirectory() as folder, override_settings(REPORTS_DIR=folder, REPORT_RECIPIENTS=['boss@example.com']):
            call_command('generate_daily_reports', '--date', DAY.isoformat(), verbosity=0)
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.to, ['boss@example.com'])
        self.assertEqual(len(message.attachments), 4)
        self.assertIn('2 transaction(s)', message.body)
        self.assertIn('0 verified, 2 still to be verified', message.body)

    def test_no_recipients_means_no_e_mail_and_no_e_mail_flag_is_respected(self):
        self.run_command('--date', DAY.isoformat())
        self.assertEqual(len(mail.outbox), 0)
        with tempfile.TemporaryDirectory() as folder, override_settings(REPORTS_DIR=folder, REPORT_RECIPIENTS=['boss@example.com']):
            call_command('generate_daily_reports', '--date', DAY.isoformat(), '--no-email', verbosity=0)
        self.assertEqual(len(mail.outbox), 0)
