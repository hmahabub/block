from unittest import mock

from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied
from django.test import TestCase, override_settings

from core.testing import make_account, make_project, make_request
from customers.models import Customer
from sales.models import CustomerPayment, FlatSale

from . import services
from .backends import LogBackend, SmsError, ZendSmsBackend, get_backend
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

            def send(self, phone, message, reference=''):
                raise SmsError('gateway down')

        with mock.patch('sms.services.get_backend', return_value=Broken()):
            log = services.notify_payment(self.pay())
        self.assertEqual((log.status, log.error), (SmsLog.Status.FAILED, 'gateway down'))

    def test_an_unexpected_gateway_error_is_also_contained(self):
        class Crashing:
            name = 'http'
            delivers = True

            def send(self, phone, message, reference=''):
                raise RuntimeError('boom')

        with mock.patch('sms.services.get_backend', return_value=Crashing()):
            log = services.notify_payment(self.pay())
        self.assertEqual(log.status, SmsLog.Status.FAILED)
        self.assertTrue(CustomerPayment.objects.exists())


ZEND = dict(
    SMS_BACKEND='zendsms', SMS_API_URL='https://api.zendsms.com/api/v1/send-sms',
    SMS_BALANCE_URL='https://api.zendsms.com/api/v1/balance', SMS_API_KEY='test-key', SMS_SENDER_ID='8809612781041',
)


def gateway_answer(body, status=200):
    """A fake urlopen result: a context manager whose read() returns `body`."""
    import json
    response = mock.MagicMock()
    response.__enter__.return_value.read.return_value = json.dumps(body).encode()
    return response


def http_error(body, code=401):
    import io
    import json
    import urllib.error
    return urllib.error.HTTPError('https://api.zendsms.com', code, 'err', {}, io.BytesIO(json.dumps(body).encode()))


@override_settings(**ZEND)
class ZendSmsBackendTests(TestCase):
    def test_it_is_chosen_by_the_setting(self):
        self.assertIsInstance(get_backend(), ZendSmsBackend)

    def test_it_posts_json_with_a_bearer_key(self):
        import json
        ok = gateway_answer({'success': True, 'code': 200, 'data': {'message_id': 'm-77', 'status': 'QUEUED'}})
        with mock.patch('urllib.request.urlopen', return_value=ok) as opened:
            message_id = ZendSmsBackend().send('+8801711000001', 'hello', 'MR-00007')
        request = opened.call_args.args[0]
        self.assertEqual((request.full_url, request.get_method()), ('https://api.zendsms.com/api/v1/send-sms', 'POST'))
        self.assertEqual(request.get_header('Authorization'), 'Bearer test-key')
        self.assertEqual(request.get_header('Content-type'), 'application/json')
        self.assertEqual(json.loads(request.data), {
            'recipient': '8801711000001', 'sender_id': '8809612781041', 'message': 'hello', 'client_ref': 'MR-00007',
        })
        self.assertEqual(message_id, 'm-77')

    def test_the_number_is_sent_without_a_plus_sign(self):
        self.assertEqual(ZendSmsBackend._recipient('+88 01711-000001'), '8801711000001')

    def test_the_client_reference_is_optional(self):
        import json
        ok = gateway_answer({'success': True, 'data': {'message_id': 'x'}})
        with mock.patch('urllib.request.urlopen', return_value=ok) as opened:
            ZendSmsBackend().send('+8801711000001', 'hello')
        self.assertNotIn('client_ref', json.loads(opened.call_args.args[0].data))

    def test_a_refusal_in_a_200_answer_is_an_error_with_the_gateways_reason(self):
        refused = gateway_answer({'success': False, 'code': 3001, 'message': 'Insufficient balance'})
        with mock.patch('urllib.request.urlopen', return_value=refused):
            with self.assertRaisesMessage(SmsError, 'Insufficient balance'):
                ZendSmsBackend().send('+8801711000001', 'hello')

    def test_an_http_error_status_uses_the_reason_in_its_body(self):
        with mock.patch('urllib.request.urlopen', side_effect=http_error({'success': False, 'code': 2001, 'message': 'Invalid API key'})):
            with self.assertRaisesMessage(SmsError, 'Invalid API key'):
                ZendSmsBackend().send('+8801711000001', 'hello')

    def test_network_trouble_is_an_error(self):
        import urllib.error
        with mock.patch('urllib.request.urlopen', side_effect=urllib.error.URLError('down')):
            with self.assertRaisesMessage(SmsError, 'not reachable'):
                ZendSmsBackend().send('+8801711000001', 'hello')

    def test_an_unreadable_answer_is_an_error(self):
        garbage = mock.MagicMock()
        garbage.__enter__.return_value.read.return_value = b'<html>oops</html>'
        with mock.patch('urllib.request.urlopen', return_value=garbage):
            with self.assertRaisesMessage(SmsError, 'Unreadable'):
                ZendSmsBackend().send('+8801711000001', 'hello')

    @override_settings(SMS_API_KEY='')
    def test_a_missing_key_is_reported_without_calling_the_gateway(self):
        with mock.patch('urllib.request.urlopen') as opened:
            with self.assertRaisesMessage(SmsError, 'SMS_API_KEY'):
                ZendSmsBackend().send('+8801711000001', 'hello')
        opened.assert_not_called()

    @override_settings(SMS_SENDER_ID='')
    def test_a_missing_sender_id_is_reported(self):
        with self.assertRaisesMessage(SmsError, 'SMS_SENDER_ID'):
            ZendSmsBackend().send('+8801711000001', 'hello')

    def test_balance_is_a_get_with_the_same_key(self):
        ok = gateway_answer({'success': True, 'code': 200, 'data': {'balance': 123.5, 'currency': 'BDT'}})
        with mock.patch('urllib.request.urlopen', return_value=ok) as opened:
            data = ZendSmsBackend().balance()
        request = opened.call_args.args[0]
        self.assertEqual((request.full_url, request.get_method()), ('https://api.zendsms.com/api/v1/balance', 'GET'))
        self.assertEqual(request.get_header('Authorization'), 'Bearer test-key')
        self.assertEqual(data, {'balance': 123.5, 'currency': 'BDT'})

    def test_the_balance_is_shown_as_readable_text(self):
        ok = gateway_answer({'success': True, 'data': {'sms_balance': 42, 'currency': 'BDT'}})
        with mock.patch('urllib.request.urlopen', return_value=ok):
            self.assertEqual(services.gateway_balance(), 'sms balance: 42, currency: BDT')

    def test_a_bad_key_on_the_balance_check_is_an_error(self):
        with mock.patch('urllib.request.urlopen', side_effect=http_error({'success': False, 'message': 'Invalid API key'})):
            with self.assertRaisesMessage(SmsError, 'Invalid API key'):
                services.gateway_balance()

    def test_the_whole_payment_path_logs_the_gateway_id(self):
        from core.testing import make_account, make_project
        _, flats = make_project()
        customer = Customer.objects.create(name='Rahim', phone='01711000001')
        sale = FlatSale.objects.create(flat=flats[0], customer=customer, sale_date='2026-01-01', sale_value=1200)
        payment = CustomerPayment.objects.create(sale=sale, payment_date='2026-02-01', amount=500, account=make_account())
        ok = gateway_answer({'success': True, 'data': {'message_id': 'zs-9001', 'status': 'QUEUED'}})
        with mock.patch('urllib.request.urlopen', return_value=ok):
            log = services.notify_payment(payment)
        self.assertEqual((log.status, log.gateway_id), (SmsLog.Status.SENT, 'zs-9001'))
        self.assertEqual(services.backend_description(), 'ZendSMS - messages are really sent')

    def test_a_rejected_payment_sms_is_logged_as_failed_with_the_reason(self):
        from core.testing import make_account, make_project
        _, flats = make_project()
        customer = Customer.objects.create(name='Rahim', phone='01711000001')
        sale = FlatSale.objects.create(flat=flats[0], customer=customer, sale_date='2026-01-01', sale_value=1200)
        payment = CustomerPayment.objects.create(sale=sale, payment_date='2026-02-01', amount=500, account=make_account())
        with mock.patch('urllib.request.urlopen', side_effect=http_error({'success': False, 'message': 'Invalid sender id'})):
            log = services.notify_payment(payment)
        self.assertEqual((log.status, log.error), (SmsLog.Status.FAILED, 'Invalid sender id'))
        self.assertTrue(CustomerPayment.objects.filter(pk=payment.pk).exists())


class SmsBalanceViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser('boss', 'b@example.com', 'pw')

    def check(self, user=None):
        from django.contrib.messages import get_messages
        from .views import SmsBalanceView
        request = make_request(user or self.user, '/sms/balance/')
        response = SmsBalanceView.as_view()(request)
        return response, [str(m) for m in get_messages(request)]

    @override_settings(**ZEND)
    def test_it_flashes_the_balance(self):
        ok = gateway_answer({'success': True, 'data': {'balance': 99}})
        with mock.patch('urllib.request.urlopen', return_value=ok):
            response, messages_ = self.check()
        self.assertEqual(response['Location'], '/sms/log/')
        self.assertEqual(messages_, ['SMS balance - balance: 99'])

    def test_without_a_gateway_it_says_so(self):
        _, messages_ = self.check()
        self.assertIn('no balance to check', messages_[0])

    def test_it_needs_the_permission(self):
        with self.assertRaises(PermissionDenied):
            self.check(User.objects.create_user('clerk'))


class LogBackendTests(TestCase):
    def test_default_backend_records_only(self):
        self.assertIsInstance(get_backend(), LogBackend)
        self.assertEqual(LogBackend().send('+8801711000001', 'hi', 'ref'), '')

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


class TestsNeverSendRealSmsTests(TestCase):
    """The test run must not reach the real gateway even when .env switches live sending on."""

    def test_the_test_run_uses_the_log_backend_and_has_no_key(self):
        from django.conf import settings
        self.assertEqual(settings.SMS_BACKEND, 'log')
        self.assertEqual(settings.SMS_API_KEY, '')
        self.assertIsInstance(get_backend(), LogBackend)
