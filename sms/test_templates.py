import re
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.messages import get_messages
from django.test import TestCase, override_settings

from core.workspace import SESSION_KEY
from core.testing import make_account, make_project, make_request
from customers.models import Customer
from projects.models import Development
from sales.models import CustomerPayment, FlatSale
from sales.views import CustomerPaymentCreateView, FlatSaleCreateView, FlatSaleUpdateView

from . import services, templating
from .models import SmsLog


class SmsTemplateTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser('boss', 'b@example.com', 'pw')
        self.estate = Development.objects.create(name='Dar Al Jannah Residency')
        self.project, self.flats = make_project('Tower 1', floors=1, units=3, base=1000, quoted=1200, parking=100)
        self.project.development = self.estate
        self.project.save()
        self.customer = Customer.objects.create(title='MR', name='Rahim Uddin', phone='01711000001')
        self.account = make_account()
        self.sale = FlatSale.objects.create(flat=self.flats[0], customer=self.customer, sale_date='2026-03-05', sale_value=1500, reg_value=50)

    def pay(self, amount=500):
        return CustomerPayment.objects.create(sale=self.sale, payment_date='2026-04-01', amount=amount, account=self.account)


class DefaultWordingTests(SmsTemplateTestCase):
    def test_the_booking_message_congratulates_and_names_the_flat(self):
        text = services.booking_message(self.sale)
        for expected in ('Congratulations', 'Mr. Rahim Uddin', 'Flat A1', 'Tower 1', self.sale.sale_no, 'Tk 1,500.00', 'Tk 1,550.00'):
            self.assertIn(expected, text)

    def test_the_booking_message_never_reveals_the_base_price_or_honorarium(self):
        text = services.booking_message(self.sale)
        self.assertNotIn('Tk 1,000.00', text)    # the base price
        self.assertNotIn('Tk 500.00', text)      # the honorarium (1500 - 1000)
        self.assertNotIn('onorarium', text)

    def test_the_payment_message_is_unchanged_by_moving_the_wording_to_env(self):
        text = services.payment_message(self.pay(500))
        self.assertEqual(
            text,
            f'Dear Mr. Rahim Uddin, we received Tk 500.00 on 01-04-2026 for flat A1, Tower 1. Receipt MR-{CustomerPayment.objects.get().pk:05d}. '
            f'Total paid Tk 500.00, balance due Tk 1,050.00. - {services._company()}',
        )

    def test_the_payment_message_ends_differently_when_paid_in_full_or_overpaid(self):
        self.assertIn('; fully paid.', services.payment_message(self.pay(1550)))
        self.assertIn('your credit balance is Tk 100.00', services.payment_message(self.pay(100)))

    def test_the_reminder_message(self):
        text = services.reminder_message(self.customer)
        for expected in ('friendly reminder', 'Tk 1,550.00', 'flat A1 (Tower 1)'):
            self.assertIn(expected, text)


class WordingFromEnvTests(SmsTemplateTestCase):
    @override_settings(SMS_TEMPLATE_BOOKING='Hello {name} ({customer_id}): {flat} in {building}, project {project}. Bye {company}')
    def test_the_wording_comes_from_the_setting(self):
        self.assertEqual(
            services.booking_message(self.sale),
            f'Hello Rahim Uddin (C0001): A1 in Tower 1, project Dar Al Jannah Residency. Bye {services._company()}',
        )

    @override_settings(SMS_TEMPLATE_PAYMENT='Paid {amount} on {date}, receipt {receipt_no}, still due {balance_due}.')
    def test_a_payment_template_can_use_its_own_placeholders(self):
        payment = self.pay(500)
        self.assertEqual(services.payment_message(payment), f'Paid Tk 500.00 on 01-04-2026, receipt {payment.receipt_no}, still due Tk 1,050.00.')

    @override_settings(SMS_TEMPLATE_REMINDER='{name} owes {total_due} ({details})')
    def test_a_reminder_template(self):
        self.assertEqual(services.reminder_message(self.customer), 'Rahim Uddin owes Tk 1,550.00 (flat A1 (Tower 1): Tk 1,550.00)')

    @override_settings(SMS_TEMPLATE_BOOKING='Hi {name}, {nonsense} and {sale_no}')
    def test_an_unknown_placeholder_is_left_as_written_so_the_typo_is_visible(self):
        text = services.booking_message(self.sale)
        self.assertEqual(text, f'Hi Rahim Uddin, {{nonsense}} and {self.sale.sale_no}')
        self.assertEqual(templating.unknown_placeholders('BOOKING'), ['nonsense'])

    @override_settings(SMS_TEMPLATE_BOOKING='{name.__class__} {name.__init__} {customer[0]} {0}')
    def test_nothing_in_a_template_can_reach_into_the_program(self):
        text = services.booking_message(self.sale)
        self.assertNotIn('class', text.replace('{name.__class__}', ''))
        self.assertEqual(text, '{name.__class__} {name.__init__} {customer[0]} {0}')

    @override_settings(SMS_TEMPLATE_BOOKING='Plain text with no placeholders at all')
    def test_a_template_without_placeholders_is_fine(self):
        self.assertEqual(services.booking_message(self.sale), 'Plain text with no placeholders at all')

    @override_settings(SMS_TEMPLATE_BOOKING='  spaced out  ')
    def test_stray_spaces_around_the_text_are_trimmed(self):
        self.assertEqual(services.booking_message(self.sale), 'spaced out')

    @override_settings(SMS_TEMPLATE_BOOKING='Flat {flat} for {customer} - {company}')
    def test_the_company_name_follows_the_company_profile(self):
        from core.models import CompanyProfile
        profile = CompanyProfile.objects.first() or CompanyProfile.objects.create()
        profile.name = 'NOORSYS Homes'
        profile.save()
        self.assertEqual(services.booking_message(self.sale), 'Flat A1 for Mr. Rahim Uddin - NOORSYS Homes')

    @override_settings(SMS_TEMPLATE_BOOKING='Welcome {project}')
    def test_a_building_without_a_project_gives_an_empty_project_name(self):
        loose, flats = make_project('Loose Tower', floors=1, units=1)
        sale = FlatSale.objects.create(flat=flats[0], customer=self.customer, sale_date='2026-03-05', sale_value=1200)
        self.assertEqual(services.booking_message(sale), 'Welcome')


class TemplateConsistencyTests(SmsTemplateTestCase):
    def test_the_default_wording_only_uses_placeholders_that_exist(self):
        for kind in templating.PLACEHOLDERS:
            self.assertEqual(templating.unknown_placeholders(kind), [], kind)

    def test_every_documented_placeholder_is_really_filled_in(self):
        payment = self.pay(10)
        values = {
            'PAYMENT': (services.payment_message, payment), 'BOOKING': (services.booking_message, self.sale),
            'REMINDER': (services.reminder_message, self.customer),
        }
        for kind, (build, subject) in values.items():
            everything = ' '.join('{%s}' % name for name in templating.PLACEHOLDERS[kind])
            with override_settings(**{templating.SETTING_NAMES[kind]: everything}):
                text = build(subject)
            self.assertNotRegex(text, r'\{\w+\}', f'{kind} left a placeholder unfilled: {text}')

    def test_the_env_example_documents_every_placeholder_and_matches_the_real_defaults(self):
        example = (Path(settings.BASE_DIR) / '.env.example').read_text(encoding='utf-8')
        for kind, setting in templating.SETTING_NAMES.items():
            match = re.search(rf'^# {setting}=(.+)$', example, re.M)
            self.assertIsNotNone(match, f'{setting} is not documented in .env.example')
            self.assertEqual(match.group(1).strip(), getattr(settings, setting), f'.env.example drifted from the default for {setting}')
            for name in templating.PLACEHOLDERS[kind]:
                self.assertIn('{' + name + '}', example, f'{{{name}}} is not described in .env.example')

    def test_the_booking_kind_is_a_known_sms_kind(self):
        self.assertIn('BOOKING', SmsLog.Kind.values)


class BookingSmsTests(SmsTemplateTestCase):
    def post_booking(self, flat, **extra):
        data = {'flat': flat.pk, 'customer': self.customer.pk, 'sale_date': '2026-05-01', 'flat_sale_value': '1300', 'reg_value': '0', **extra}
        request = make_request(self.user, '/sales/create/', 'post', data)
        response = FlatSaleCreateView.as_view()(request)
        return response, [str(m) for m in get_messages(request)]

    def test_booking_a_flat_sends_the_customer_an_sms_automatically(self):
        SmsLog.objects.all().delete()
        response, _ = self.post_booking(self.flats[1])
        self.assertEqual(response.status_code, 302)
        log = SmsLog.objects.get()
        self.assertEqual((log.kind, log.customer, log.phone), (SmsLog.Kind.BOOKING, self.customer, '+8801711000001'))
        self.assertIn('Congratulations', log.message)
        self.assertIn('B1', log.message)

    def test_the_gateway_gets_the_sale_number_as_its_reference(self):
        class Gateway:
            name, delivers = 'zendsms', True
            calls = []

            def send(self, phone, message, reference=''):
                self.calls.append((phone, reference))
                return 'm-1'

        gateway = Gateway()
        with mock.patch('sms.services.get_backend', return_value=gateway):
            self.post_booking(self.flats[1])
        sale = FlatSale.objects.get(flat=self.flats[1])
        self.assertEqual(gateway.calls, [('+8801711000001', sale.sale_no)])

    def test_the_screen_says_whether_it_was_delivered(self):
        _, text = self.post_booking(self.flats[1])
        self.assertTrue(any('Booking saved, but the SMS' in m and 'NOT delivered' in m for m in text), text)

    def test_a_customer_excluded_from_sms_gets_nothing_but_the_booking_still_saves(self):
        self.customer.sms_enabled = False
        self.customer.save()
        SmsLog.objects.all().delete()
        _, text = self.post_booking(self.flats[1])
        self.assertEqual(SmsLog.objects.count(), 0)
        self.assertTrue(FlatSale.objects.filter(flat=self.flats[1]).exists())
        self.assertTrue(any('excluded from SMS' in m for m in text))

    def test_a_failing_gateway_never_stops_the_booking(self):
        from .backends import SmsError

        class Broken:
            name, delivers = 'zendsms', True

            def send(self, phone, message, reference=''):
                raise SmsError('gateway down')

        with mock.patch('sms.services.get_backend', return_value=Broken()):
            _, text = self.post_booking(self.flats[1])
        self.assertTrue(FlatSale.objects.filter(flat=self.flats[1]).exists())
        self.assertEqual(SmsLog.objects.filter(kind='BOOKING').get().status, 'FAILED')
        self.assertTrue(any('could not be sent: gateway down' in m for m in text))

    def test_a_refused_booking_form_sends_nothing(self):
        SmsLog.objects.all().delete()
        self.post_booking(self.flats[1], flat_sale_value='1')      # below the base price: the form is invalid
        self.assertEqual(SmsLog.objects.count(), 0)

    def test_editing_a_sale_does_not_send_another_booking_sms(self):
        SmsLog.objects.all().delete()
        data = {'flat': self.sale.flat_id, 'customer': self.customer.pk, 'sale_date': '2026-03-05', 'flat_sale_value': '1600', 'reg_value': '50'}
        FlatSaleUpdateView.as_view()(make_request(self.user, '/', 'post', data), pk=self.sale.pk)
        self.assertEqual(SmsLog.objects.filter(kind='BOOKING').count(), 0)

    def test_the_payment_sms_still_goes_out_automatically_with_its_own_wording(self):
        SmsLog.objects.all().delete()
        data = {'invoice': self.sale.booking_invoice.pk, 'payment_date': '2026-04-02', 'amount': '400', 'account': self.account.pk}
        CustomerPaymentCreateView.as_view()(make_request(self.user, '/', 'post', data, session={SESSION_KEY: self.estate.pk}))
        log = SmsLog.objects.get()
        self.assertEqual(log.kind, SmsLog.Kind.PAYMENT)
        self.assertIn('Tk 400.00', log.message)

    @override_settings(SMS_TEMPLATE_BOOKING='Booked {flat}!')
    def test_the_booking_sms_uses_the_wording_in_env(self):
        SmsLog.objects.all().delete()
        self.post_booking(self.flats[1])
        self.assertEqual(SmsLog.objects.get().message, 'Booked B1!')
