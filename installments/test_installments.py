"""Installments: issued to every customer of a project, added as due on each account, with an SMS giving the deadline."""
import datetime
from decimal import Decimal
from io import BytesIO

from django.contrib.auth.models import Permission, User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from openpyxl import load_workbook

from core.testing import enter_project, make_account, make_project, unlock_client
from customers.models import Customer
from projects.models import Development
from sales.models import CustomerPayment, FlatSale
from sms.models import SmsLog

from . import services
from .forms import IssueInstallmentForm
from .models import Installment, InstallmentCharge

D = Decimal
TODAY = timezone.localdate()
LATER = TODAY + datetime.timedelta(days=20)


class InstallmentTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser('boss', 'b@example.com', 'pw')
        self.development = Development.objects.create(name='Estate')
        # base 1000, parking 100, quoted 1200
        self.building, self.flats = make_project('Tower', floors=1, units=4, development=self.development)
        self.bank = make_account('Bank 1')
        self.rahim = self.customer('Rahim', '01711000001')
        self.karim = self.customer('Karim', '01711000002')
        self.salma = self.customer('Salma', '01711000003')
        # net values 2000, 2000, 1500
        self.rahim_sale = self.book(self.flats[0], self.rahim, 2000)
        self.karim_sale = self.book(self.flats[1], self.karim, 2000)
        self.salma_sale = self.book(self.flats[2], self.salma, 1500)

    def customer(self, name, phone):
        return Customer.objects.create(name=name, phone=phone)

    def book(self, flat, customer, value):
        return FlatSale.objects.create(flat=flat, customer=customer, sale_date='2026-01-01', sale_value=value)

    def pay(self, sale, amount, date=None, invoice=None):
        """A payment under the invoice named (the flat booking's invoice when none is)."""
        return CustomerPayment.objects.create(
            sale=sale, payment_date=date or TODAY, amount=amount, account=self.bank, invoice=invoice or sale.booking_invoice)

    def pay_installment(self, sale, amount, installment, date=None):
        """A payment under the installment's invoice of this booking."""
        return self.pay(sale, amount, date, invoice=installment.charges.get(sale=sale).invoice)

    def issue(self, value=500, basis='FIXED', due=LATER, title='Installment 1', **extra):
        return services.issue(self.development, self.user, title, due, basis, D(value), **extra)

    def refresh(self, sale):
        return FlatSale.objects.get(pk=sale.pk)

    def rows_of(self, sale):
        return services.allocate(self.refresh(sale))


class IssuingTests(InstallmentTestCase):
    def test_every_booking_in_the_project_is_charged(self):
        installment = self.issue(500)
        self.assertEqual(installment.charges.count(), 3)
        self.assertEqual({c.amount for c in installment.charges.all()}, {500})
        self.assertEqual(installment.number, 1)

    def test_the_amount_is_due_on_each_customers_account(self):
        self.issue(500)
        for sale in (self.rahim_sale, self.karim_sale, self.salma_sale):
            rows = self.rows_of(sale)
            self.assertEqual((rows[0].due, rows[0].status), (500, services.DUE))

    def test_numbers_count_up_per_project(self):
        self.assertEqual(self.issue(100, title='A').number, 1)
        self.assertEqual(self.issue(100, title='B').number, 2)
        other = Development.objects.create(name='Other')
        make_project('Villa', floors=1, units=1, development=other)
        self.assertEqual(services.issue(other, self.user, 'First', LATER, 'FIXED', D(10)).number, 1)

    def test_a_percentage_of_each_sale_value(self):
        installment = self.issue(10, basis='PERCENT')
        amounts = {c.sale_id: c.amount for c in installment.charges.all()}
        self.assertEqual(amounts, {self.rahim_sale.pk: 200, self.karim_sale.pk: 200, self.salma_sale.pk: 150})

    def test_cancelled_bookings_are_not_charged(self):
        self.salma_sale.cancel(100)
        self.salma_sale.save()
        installment = self.issue(500)
        self.assertEqual(installment.charges.count(), 2)
        self.assertFalse(installment.charges.filter(sale=self.salma_sale).exists())

    def test_one_building_only(self):
        other_building, flats = make_project('Villa', floors=1, units=1, development=self.development)
        villa = self.book(flats[0], self.rahim, 3000)
        installment = self.issue(500, building=other_building)
        self.assertEqual([c.sale for c in installment.charges.all()], [villa])

    def test_other_projects_are_never_charged(self):
        other = Development.objects.create(name='Other')
        building, flats = make_project('Villa', floors=1, units=1, development=other)
        far = self.book(flats[0], self.rahim, 3000)
        self.issue(500)
        self.assertFalse(InstallmentCharge.objects.filter(sale=far).exists())

    def test_what_was_paid_for_the_flat_booking_cannot_be_charged_again(self):
        self.pay(self.rahim_sale, 700)                                  # booking money
        installment = self.issue(2000)
        self.assertEqual(installment.charges.get(sale=self.rahim_sale).amount, 1300)      # net 2000 - 700
        self.assertEqual(installment.charges.get(sale=self.karim_sale).amount, 2000)


class PayingTests(InstallmentTestCase):
    def test_a_payment_for_the_flat_booking_never_pays_an_installment(self):
        self.issue(500)
        self.pay(self.rahim_sale, 700)            # booking money, even though it came after the installment
        rows = self.rows_of(self.rahim_sale)
        self.assertEqual((rows[0].paid, rows[0].due), (0, 500))

    def test_a_payment_for_the_installment_pays_it_off(self):
        self.pay(self.rahim_sale, 700)
        installment = self.issue(500)
        self.pay_installment(self.rahim_sale, 300, installment)
        row = self.rows_of(self.rahim_sale)[0]
        self.assertEqual((row.paid, row.due, row.status), (300, 200, services.PART))
        self.pay_installment(self.rahim_sale, 200, installment)
        row = self.rows_of(self.rahim_sale)[0]
        self.assertEqual((row.paid, row.due, row.status), (500, 0, services.PAID))

    def test_a_payment_names_the_installment_it_pays(self):
        sooner = self.issue(400, title='Sooner', due=LATER)
        later = self.issue(500, title='Later', due=LATER + datetime.timedelta(days=30))
        self.pay_installment(self.rahim_sale, 300, later)           # the later one, although the sooner is due first
        rows = {r.installment.title: r for r in self.rows_of(self.rahim_sale)}
        self.assertEqual((rows['Sooner'].paid, rows['Later'].paid), (0, 300))

    def test_a_missed_deadline_is_overdue(self):
        installment = self.issue(500, due=TODAY - datetime.timedelta(days=3))
        row = self.rows_of(self.rahim_sale)[0]
        self.assertEqual((row.status, row.due), (services.OVERDUE, 500))
        self.pay_installment(self.rahim_sale, 500, installment)
        self.assertEqual(self.rows_of(self.rahim_sale)[0].status, services.PAID)

    def test_never_more_than_the_installments_is_applied(self):
        installment = self.issue(500)
        self.pay_installment(self.rahim_sale, 900, installment)     # the form refuses this; the sums still hold
        row = self.rows_of(self.rahim_sale)[0]
        self.assertEqual((row.paid, row.due), (500, 0))

    def test_totals_for_a_customer(self):
        first = self.issue(500, due=TODAY - datetime.timedelta(days=1))
        self.issue(300, title='Installment 2')
        self.pay_installment(self.rahim_sale, 100, first)
        self.assertEqual(services.customer_due(self.rahim, self.development), (700, 400))
        self.assertEqual(services.customer_due(self.rahim, Development.objects.create(name='Other')), (0, 0))

    def test_a_cancelled_booking_owes_nothing(self):
        self.issue(500)
        self.rahim_sale.cancel(100)
        self.rahim_sale.save()
        self.assertEqual(services.customer_due(self.rahim, self.development), (0, 0))

    def test_the_payment_says_in_words_what_it_was_for(self):
        installment = self.issue(500, title='Installment 1')
        self.assertEqual(self.pay(self.rahim_sale, 10).purpose_text, 'Flat booking')
        self.assertEqual(self.pay_installment(self.rahim_sale, 10, installment).purpose_text, 'Installment 1')


class LimitsTests(InstallmentTestCase):
    def test_nothing_beyond_the_net_value_can_be_charged(self):
        self.pay(self.salma_sale, 1000)           # net 1500, so 500 left to charge
        installment = self.issue(800)
        self.assertEqual(installment.charges.get(sale=self.salma_sale).amount, 500)     # reduced to what is left
        self.assertEqual(installment.charges.get(sale=self.rahim_sale).amount, 800)

    def test_a_fully_scheduled_booking_is_left_out(self):
        self.issue(1500)
        again = self.issue(500, title='Second')
        self.assertEqual(again.charges.get(sale=self.rahim_sale).amount, 500)
        self.assertFalse(again.charges.filter(sale=self.salma_sale).exists())       # 1500 of 1500 already charged

    def test_the_preview_says_who_is_left_out_and_who_is_reduced(self):
        self.pay(self.salma_sale, 1000)
        rows, skipped = services.preview(self.development, None, 'FIXED', D(800))
        self.assertEqual(sum(1 for *_, capped in rows if capped), 1)
        self.issue(2000, title='Everything')
        rows, skipped = services.preview(self.development, None, 'FIXED', D(100))
        self.assertEqual(rows, [])
        self.assertEqual(len(skipped), 3)


class SmsTests(InstallmentTestCase):
    def test_every_customer_is_told_the_amount_and_the_deadline(self):
        installment = self.issue(500)
        services.notify_all(installment.issued_charges, self.user)
        logs = SmsLog.objects.filter(kind=SmsLog.Kind.INSTALLMENT)
        self.assertEqual(logs.count(), 3)
        text = logs.get(customer=self.rahim).message
        for expected in ('Rahim', 'Installment 1', 'Tk 500.00', f'{LATER:%d-%m-%Y}', self.flats[0].flat_no):
            self.assertIn(expected, text)

    def test_the_message_says_what_is_due_in_total_on_the_flat(self):
        self.issue(500)
        second = self.issue(300, title='Installment 2')
        services.notify_installment(second.charges.get(sale=self.rahim_sale))
        self.assertIn('Tk 800.00', SmsLog.objects.get(kind='INSTALLMENT').message)

    def test_customers_excluded_from_sms_are_skipped(self):
        self.karim.sms_enabled = False
        self.karim.save()
        counts = services.notify_all(self.issue(500).issued_charges)
        self.assertEqual(counts, {'LOGGED': 2, 'EXCLUDED': 1})

    def test_the_time_of_the_sms_is_recorded(self):
        installment = self.issue(500)
        services.notify_all(installment.issued_charges)
        self.assertEqual(installment.charges.filter(notified_at__isnull=False).count(), 3)

    def test_the_wording_comes_from_the_settings(self):
        from django.test import override_settings

        with override_settings(SMS_TEMPLATE_INSTALLMENT='Pay {amount} by {deadline} ({installment}) {unknown}'):
            charge = self.issue(500).charges.get(sale=self.rahim_sale)
            self.assertEqual(services.installment_message(charge), f'Pay Tk 500.00 by {LATER:%d-%m-%Y} (Installment 1) {{unknown}}')


class WithdrawTests(InstallmentTestCase):
    def test_an_unpaid_installment_can_be_withdrawn(self):
        self.pay(self.rahim_sale, 700)
        installment = self.issue(500)
        self.assertTrue(services.withdraw(installment))
        self.assertFalse(Installment.objects.exists())

    def test_one_that_has_been_paid_towards_cannot(self):
        installment = self.issue(500)
        self.pay_installment(self.rahim_sale, 100, installment)
        self.assertFalse(services.withdraw(installment))
        self.assertTrue(Installment.objects.filter(pk=installment.pk).exists())

    def test_withdrawing_one_keeps_the_others_schedule(self):
        first = self.issue(500)
        second = self.issue(300, title='Installment 2')
        services.withdraw(second)
        self.assertEqual(len(self.rows_of(self.rahim_sale)), 1)
        self.assertEqual(first.charges.count(), 3)


class FormTests(InstallmentTestCase):
    def form(self, **data):
        base = {'title': 'Installment 1', 'due_date': LATER.isoformat(), 'basis': 'FIXED', 'value': '500', **data}
        return IssueInstallmentForm(data=base, development=self.development)

    def test_a_good_form(self):
        self.assertTrue(self.form().is_valid())

    def test_the_deadline_cannot_be_in_the_past(self):
        form = self.form(due_date=(TODAY - datetime.timedelta(days=1)).isoformat())
        self.assertFalse(form.is_valid())
        self.assertIn('due_date', form.errors)

    def test_a_percentage_cannot_exceed_100(self):
        form = self.form(basis='PERCENT', value='150')
        self.assertFalse(form.is_valid())
        self.assertIn('value', form.errors)

    def test_the_amount_must_be_positive(self):
        self.assertFalse(self.form(value='0').is_valid())

    def test_only_this_projects_buildings_are_offered(self):
        other = Development.objects.create(name='Other')
        far, _ = make_project('Villa', floors=1, units=1, development=other)
        form = self.form(building=far.pk)
        self.assertFalse(form.is_valid())
        self.assertEqual(list(form.fields['building'].queryset), [self.building])


class ScreenTests(InstallmentTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.user)
        unlock_client(self.client)
        enter_project(self.client, self.development)

    def data(self, **extra):
        return {'title': 'Installment 1', 'due_date': LATER.isoformat(), 'basis': 'FIXED', 'value': '500', 'building': '',
                'notes': '', 'send_sms': 'on', **extra}

    def test_the_list_page(self):
        self.issue(500)
        page = self.client.get(reverse('installments:list')).content.decode()
        self.assertIn('Installment 1', page)
        self.assertIn('1,500.00', page)         # 3 customers x 500 due

    def test_issuing_first_shows_who_will_be_charged_and_saves_nothing(self):
        response = self.client.post(reverse('installments:issue'), self.data())
        self.assertEqual(response.status_code, 200)
        page = response.content.decode()
        self.assertIn('Rahim', page)
        self.assertIn('3 customer account', page)
        self.assertIn('name="confirm" value="1"', page)
        self.assertFalse(Installment.objects.exists())
        self.assertFalse(SmsLog.objects.exists())

    def test_confirming_issues_it_and_sends_the_sms(self):
        response = self.client.post(reverse('installments:issue'), self.data(confirm='1'))
        installment = Installment.objects.get()
        self.assertRedirects(response, installment.get_absolute_url())
        self.assertEqual(installment.charges.count(), 3)
        self.assertEqual(SmsLog.objects.filter(kind='INSTALLMENT').count(), 3)

    def test_without_the_sms_box_nobody_is_texted(self):
        data = self.data(confirm='1')
        del data['send_sms']
        self.client.post(reverse('installments:issue'), data)
        self.assertEqual(Installment.objects.get().charges.count(), 3)
        self.assertFalse(SmsLog.objects.exists())

    def test_an_invalid_form_is_shown_again(self):
        response = self.client.post(reverse('installments:issue'), self.data(due_date='2000-01-01'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'cannot be in the past')
        self.assertFalse(Installment.objects.exists())

    def test_the_detail_page_and_its_filters(self):
        installment = self.issue(500)
        self.pay_installment(self.rahim_sale, 500, installment)
        url = reverse('installments:detail', args=[installment.pk])
        everyone = self.client.get(url).context['rows']
        self.assertEqual(len(everyone), 3)
        self.assertEqual(len(self.client.get(url, {'show': 'paid'}).context['rows']), 1)
        self.assertEqual(len(self.client.get(url, {'show': 'unpaid'}).context['rows']), 2)
        self.assertEqual(len(self.client.get(url, {'show': 'overdue'}).context['rows']), 0)
        page = self.client.get(url).content.decode()
        self.assertIn('Payment deadline', page)

    def test_the_excel_file(self):
        installment = self.issue(500)
        response = self.client.get(reverse('installments:detail', args=[installment.pk]), {'format': 'xlsx'})
        cells = {str(c.value) for row in load_workbook(BytesIO(response.content)).active.iter_rows() for c in row}
        for text in ('Rahim', 'Karim', 'Due', '500'):
            self.assertTrue(any(text in cell for cell in cells), text)

    def test_sending_the_sms_again_goes_only_to_those_who_have_not_paid(self):
        installment = self.issue(500)
        self.pay_installment(self.rahim_sale, 500, installment)
        self.client.post(reverse('installments:send-sms', args=[installment.pk]))
        self.assertEqual(SmsLog.objects.filter(kind='INSTALLMENT').count(), 2)
        self.assertFalse(SmsLog.objects.filter(customer=self.rahim).exists())

    def test_withdrawing_through_the_page(self):
        installment = self.issue(500)
        self.client.post(reverse('installments:withdraw', args=[installment.pk]))
        self.assertFalse(Installment.objects.exists())

    def test_the_sale_page_lists_its_installments(self):
        installment = self.issue(500)
        self.pay_installment(self.rahim_sale, 200, installment)
        page = self.client.get(reverse('sales:detail', args=[self.rahim_sale.pk])).content.decode()
        self.assertIn('Installment 1', page)
        self.assertIn('Partly paid', page)

    def test_the_customer_page_shows_what_is_due_now(self):
        self.issue(500, due=TODAY - datetime.timedelta(days=2))
        page = self.client.get(reverse('customers:detail', args=[self.rahim.pk])).content.decode()
        self.assertIn('Installments due now', page)
        self.assertIn('past the deadline', page)

    def test_the_menu_links_to_it(self):
        self.assertIn(reverse('installments:list'), self.client.get(reverse('home')).content.decode())


class AccessTests(InstallmentTestCase):
    def test_it_needs_a_project(self):
        self.client.force_login(self.user)
        unlock_client(self.client)
        self.assertRedirects(self.client.get(reverse('installments:list')), reverse('home'))

    def test_another_projects_installment_is_not_found(self):
        installment = self.issue(500)
        self.client.force_login(self.user)
        unlock_client(self.client)
        enter_project(self.client, Development.objects.create(name='Other'))
        for name in ('installments:detail', 'installments:send-sms', 'installments:withdraw'):
            method = self.client.get if name.endswith('detail') else self.client.post
            self.assertEqual(method(reverse(name, args=[installment.pk])).status_code, 404, name)

    def test_issuing_needs_the_permission(self):
        clerk = User.objects.create_user('clerk', password='pw')
        clerk.user_permissions.add(Permission.objects.get(codename='view_installment'))
        self.client.force_login(clerk)
        unlock_client(self.client)
        enter_project(self.client, self.development)
        self.assertEqual(self.client.get(reverse('installments:issue')).status_code, 403)
        installment = self.issue(500)
        self.assertEqual(self.client.post(reverse('installments:send-sms', args=[installment.pk])).status_code, 403)
        self.assertEqual(self.client.post(reverse('installments:withdraw', args=[installment.pk])).status_code, 403)

    def test_it_asks_for_the_password_while_the_screens_are_locked(self):
        self.client.force_login(self.user)
        enter_project(self.client, self.development)
        response = self.client.get(reverse('installments:list'))
        self.assertIn('/confirm-password/', response['Location'])
