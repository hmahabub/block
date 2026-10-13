from unittest import mock

from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied
from django.test import TestCase, override_settings

from core.testing import make_account, make_project, make_request
from customers.models import Customer
from sales.models import CustomerPayment, FlatSale

from . import services
from .backends import HttpBackend, LogBackend, SmsError, get_backend
from .models import SmsLog
from .views import ReminderView, SendRemindersView


class SmsTestCase(TestCase):
    def setUp(self):
        self.project, self.flats = make_project('Tower 1')
        self.account = make_account()
        self.customer = Customer.objects.create(title='MR', name='Rahim', phone='01711000001')
        self.sale = FlatSale.objects.create(
            flat=self.flats[0], customer=self.customer, sale_date='2026-01-01', sale_value=1200,
        )

    def pay(self, amount=500):
        return CustomerPayment.objects.create(
            sale=self.sale, payment_date='2026-02-01', amount=amount, account=self.account,
        )


class PaymentSmsTests(SmsTestCase):
    def test_the_message_names_the_amount_flat_receipt_and_balance(self):
        text = services.payment_message(self.pay(500))
        for expected in ('Mr. Rahim', 'Tk 500.00', 'A1', 'Tower 1', 'MR-', 'balance due Tk 700.00'):
            self.assertIn(expected, text)

    def test_a_full_payment_says_fully_paid(self):
        self.assertIn('fully paid', services.payment_message(self.pay(1200)))

    def test_an_overpayment_mentions_the_credit(self):
        self.assertIn('credit balance is Tk 100.00', services.payment_message(self.pay(1300)))

    def test_default_backend_only_records_the_message(self):
        log = services.notify_payment(self.pay())
        self.assertEqual((log.status, log.kind, log.phone), (SmsLog.Status.LOGGED, SmsLog.Kind.PAYMENT, '+8801711000001'))
        self.assertIsInstance(get_backend(), LogBackend)

    def test_excluded_customers_get_nothing(self):
        self.customer.sms_enabled = False
        self.customer.save()
        self.assertIsNone(services.notify_payment(self.pay()))
        self.assertEqual(SmsLog.objects.count(), 0)

    def test_a_gateway_failure_is_recorded_and_never_raised(self):
        class Broken:
            name = 'http'
            delivers = True

            def send(self, phone, message):
                raise SmsError('gateway down')

        with mock.patch('sms.services.get_backend', return_value=Broken()):
            log = services.notify_payment(self.pay())
        self.assertEqual((log.status, log.error), (SmsLog.Status.FAILED, 'gateway down'))

    def test_an_unexpected_gateway_error_is_also_contained(self):
        class Crashing:
            name = 'http'
            delivers = True

            def send(self, phone, message):
                raise RuntimeError('boom')

        with mock.patch('sms.services.get_backend', return_value=Crashing()):
            log = services.notify_payment(self.pay())
        self.assertEqual(log.status, SmsLog.Status.FAILED)
        self.assertTrue(CustomerPayment.objects.exists())


class HttpBackendTests(TestCase):
    @override_settings(SMS_BACKEND='http', SMS_API_URL='', SMS_API_KEY='k', SMS_SENDER_ID='S')
    def test_needs_a_url(self):
        self.assertIsInstance(get_backend(), HttpBackend)
        with self.assertRaises(SmsError):
            HttpBackend().send('+8801711000001', 'hi')

    @override_settings(SMS_BACKEND='http', SMS_API_URL='https://sms.example.com/api', SMS_API_KEY='k', SMS_SENDER_ID='S')
    def test_posts_the_message_and_reads_the_gateway_answer(self):
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = b'{"response_code": 202}'
        with mock.patch('urllib.request.urlopen', return_value=response) as opened:
            HttpBackend().send('+8801711000001', 'hello')
        request = opened.call_args.args[0]
        body = request.data.decode()
        self.assertIn('number=8801711000001', body)
        self.assertIn('api_key=k', body)
        self.assertIn('senderid=S', body)
        self.assertIn('message=hello', body)

    @override_settings(SMS_BACKEND='http', SMS_API_URL='https://sms.example.com/api')
    def test_a_rejection_from_the_gateway_is_an_error(self):
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = b'{"response_code": 1007, "error_message": "Low balance"}'
        with mock.patch('urllib.request.urlopen', return_value=response):
            with self.assertRaisesMessage(SmsError, 'Low balance'):
                HttpBackend().send('+8801711000001', 'hello')

    @override_settings(SMS_BACKEND='http', SMS_API_URL='https://sms.example.com/api')
    def test_network_trouble_is_an_error(self):
        import urllib.error
        with mock.patch('urllib.request.urlopen', side_effect=urllib.error.URLError('down')):
            with self.assertRaises(SmsError):
                HttpBackend().send('+8801711000001', 'hello')

    def test_an_unknown_backend_name_falls_back_to_logging(self):
        with override_settings(SMS_BACKEND='nonsense'):
            self.assertIsInstance(get_backend(), LogBackend)


class ReminderTests(SmsTestCase):
    def test_only_customers_with_a_balance_are_listed(self):
        paid = Customer.objects.create(name='Paid Up', phone='01711000002')
        sale = FlatSale.objects.create(flat=self.flats[1], customer=paid, sale_date='2026-01-01', sale_value=1000)
        CustomerPayment.objects.create(sale=sale, payment_date='2026-01-02', amount=1000, account=self.account)
        self.assertEqual([c.name for c in services.customers_with_dues()], ['Rahim'])

    def test_a_cancelled_booking_owes_nothing(self):
        self.sale.cancel(100)
        self.sale.save()
        self.assertEqual(services.customers_with_dues(), [])
        self.assertEqual(services.reminder_message(self.customer), '')

    def test_the_reminder_lists_each_flat_and_the_total(self):
        FlatSale.objects.create(flat=self.flats[1], customer=self.customer, sale_date='2026-01-01', sale_value=800)
        text = services.reminder_message(self.customer)
        for expected in ('Mr. Rahim', 'Tk 2,000.00', 'flat A1', 'flat B1', 'Tk 1,200.00', 'Tk 800.00'):
            self.assertIn(expected, text)

    def test_nothing_is_sent_until_someone_asks(self):
        self.pay()
        self.assertEqual(SmsLog.objects.filter(kind=SmsLog.Kind.REMINDER).count(), 0)

    def test_sending_reminders_logs_each_one(self):
        sent, skipped = services.send_reminders([self.customer], user=None)
        self.assertEqual((sent, skipped), ([self.customer], []))
        self.assertEqual(SmsLog.objects.get().kind, SmsLog.Kind.REMINDER)

    def test_excluded_customers_are_skipped_even_when_ticked(self):
        self.customer.sms_enabled = False
        self.customer.save()
        sent, skipped = services.send_reminders([self.customer], user=None)
        self.assertEqual((sent, skipped), ([], [self.customer]))
        self.assertEqual(SmsLog.objects.count(), 0)

    def test_customers_with_nothing_due_are_skipped(self):
        self.sale.cancel(100)
        self.sale.save()
        sent, skipped = services.send_reminders([self.customer], user=None)
        self.assertEqual((sent, skipped), ([], [self.customer]))

    def test_the_send_view_sends_only_to_ticked_customers(self):
        other = Customer.objects.create(name='Other', phone='01711000003')
        FlatSale.objects.create(flat=self.flats[1], customer=other, sale_date='2026-01-01', sale_value=900)
        user = User.objects.create_superuser('boss', 'b@example.com', 'pw')
        request = make_request(user, '/', 'post', {'customers': [self.customer.pk]})
        response = SendRemindersView.as_view()(request)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(list(SmsLog.objects.values_list('customer__name', flat=True)), ['Rahim'])

    def test_the_send_view_with_nothing_ticked_does_nothing(self):
        user = User.objects.create_superuser('boss', 'b@example.com', 'pw')
        SendRemindersView.as_view()(make_request(user, '/', 'post', {}))
        self.assertEqual(SmsLog.objects.count(), 0)

    def test_sending_needs_permission(self):
        clerk = User.objects.create_user('clerk')
        with self.assertRaises(PermissionDenied):
            SendRemindersView.as_view()(make_request(clerk, '/', 'post', {'customers': [self.customer.pk]}))
        self.assertEqual(SmsLog.objects.count(), 0)

    def test_the_reminder_screen_marks_excluded_customers(self):
        self.customer.sms_enabled = False
        self.customer.save()
        user = User.objects.create_superuser('boss', 'b@example.com', 'pw')
        view = ReminderView()
        view.setup(make_request(user, '/'))
        customers = view.get_context_data()['customers']
        self.assertEqual([(c.name, c.sms_enabled) for c in customers], [('Rahim', False)])
