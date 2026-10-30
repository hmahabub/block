import io
import json
import urllib.error
from unittest import mock
from urllib.parse import parse_qs, urlparse

from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from core.testing import make_account, make_project, make_request
from customers.models import Customer
from sales.models import CustomerPayment, FlatSale

from . import services
from .backends import SmsError, SmsNetBdBackend, ZendSmsBackend, get_backend
from .models import SmsLog

NETBD = dict(
    SMS_BACKEND='smsnetbd', SMSNETBD_API_URL='https://api.sms.net.bd/sendsms',
    SMSNETBD_BALANCE_URL='https://api.sms.net.bd/user/balance/', SMSNETBD_API_KEY='test-key', SMSNETBD_SENDER_ID='',
)


def answer(body):
    """A fake urlopen result. The real gateway answers every request with HTTP 200 and a JSON body."""
    response = mock.MagicMock()
    response.__enter__.return_value.read.return_value = json.dumps(body).encode()
    return response


OK = {'error': 0, 'msg': 'Request successfully submitted', 'data': {'request_id': 4242}}


@override_settings(**NETBD)
class SmsNetBdBackendTests(TestCase):
    def test_it_is_chosen_by_the_setting(self):
        self.assertIsInstance(get_backend(), SmsNetBdBackend)
        self.assertTrue(get_backend().delivers)

    def test_it_posts_the_key_message_and_number_as_a_form(self):
        with mock.patch('urllib.request.urlopen', return_value=answer(OK)) as opened:
            request_id = SmsNetBdBackend().send('+8801711000001', 'Hello there', 'MR-00001')
        request = opened.call_args.args[0]
        self.assertEqual((request.full_url, request.get_method()), ('https://api.sms.net.bd/sendsms', 'POST'))
        fields = parse_qs(request.data.decode())
        self.assertEqual(fields, {'api_key': ['test-key'], 'msg': ['Hello there'], 'to': ['8801711000001']})
        self.assertEqual(request_id, '4242')

    def test_the_number_goes_with_the_country_code_and_no_plus(self):
        self.assertEqual(SmsNetBdBackend._recipient('+88 01711-000001'), '8801711000001')

    def test_the_message_is_url_encoded_so_symbols_and_bangla_survive(self):
        text = 'Paid Tk 1,500.00 & thanks: 100% ধন্যবাদ'
        with mock.patch('urllib.request.urlopen', return_value=answer(OK)) as opened:
            SmsNetBdBackend().send('+8801711000001', text)
        self.assertEqual(parse_qs(opened.call_args.args[0].data.decode())['msg'], [text])

    @override_settings(SMSNETBD_SENDER_ID='MyCompany')
    def test_an_approved_sender_id_is_sent_when_set(self):
        with mock.patch('urllib.request.urlopen', return_value=answer(OK)) as opened:
            SmsNetBdBackend().send('+8801711000001', 'hi')
        self.assertEqual(parse_qs(opened.call_args.args[0].data.decode())['sender_id'], ['MyCompany'])

    def test_no_sender_id_is_sent_when_none_is_set(self):
        with mock.patch('urllib.request.urlopen', return_value=answer(OK)) as opened:
            SmsNetBdBackend().send('+8801711000001', 'hi')
        self.assertNotIn('sender_id', parse_qs(opened.call_args.args[0].data.decode()))

    def test_a_refusal_comes_back_as_http_200_with_an_error_code(self):
        for code, text in ((405, 'Authorization required'), (417, 'Insufficient balance'), (413, 'Invalid Sender ID'), (420, 'Content blocked')):
            with mock.patch('urllib.request.urlopen', return_value=answer({'error': code, 'msg': text})):
                with self.assertRaises(SmsError) as caught:
                    SmsNetBdBackend().send('+8801711000001', 'hello')
            self.assertEqual(str(caught.exception), f'{text} (code {code})')

    def test_an_http_error_status_uses_the_reason_in_its_body(self):
        error = urllib.error.HTTPError('https://api.sms.net.bd', 500, 'err', {}, io.BytesIO(b'{"error": 409, "msg": "Unknown error"}'))
        with mock.patch('urllib.request.urlopen', side_effect=error):
            with self.assertRaisesMessage(SmsError, 'Unknown error (code 409)'):
                SmsNetBdBackend().send('+8801711000001', 'hello')

    def test_network_trouble_is_an_error(self):
        with mock.patch('urllib.request.urlopen', side_effect=urllib.error.URLError('down')):
            with self.assertRaisesMessage(SmsError, 'not reachable'):
                SmsNetBdBackend().send('+8801711000001', 'hello')

    def test_an_unreadable_answer_is_an_error(self):
        garbage = mock.MagicMock()
        garbage.__enter__.return_value.read.return_value = b'<html>maintenance</html>'
        with mock.patch('urllib.request.urlopen', return_value=garbage):
            with self.assertRaisesMessage(SmsError, 'Unreadable'):
                SmsNetBdBackend().send('+8801711000001', 'hello')

    @override_settings(SMSNETBD_API_KEY='')
    def test_a_missing_key_is_reported_without_calling_the_gateway(self):
        with mock.patch('urllib.request.urlopen') as opened:
            with self.assertRaisesMessage(SmsError, 'SMSNETBD_API_KEY'):
                SmsNetBdBackend().send('+8801711000001', 'hello')
            with self.assertRaisesMessage(SmsError, 'SMSNETBD_API_KEY'):
                SmsNetBdBackend().balance()
        opened.assert_not_called()

    def test_the_balance_is_a_get_with_the_key_in_the_query(self):
        reply = {'error': 0, 'msg': 'Success', 'data': {'balance': '57.2500'}}
        with mock.patch('urllib.request.urlopen', return_value=answer(reply)) as opened:
            data = SmsNetBdBackend().balance()
        request = opened.call_args.args[0]
        target = urlparse(request.full_url)
        self.assertEqual((request.get_method(), target.netloc + target.path), ('GET', 'api.sms.net.bd/user/balance/'))
        self.assertEqual(parse_qs(target.query), {'api_key': ['test-key']})
        self.assertEqual(data, {'balance': '57.2500'})

    def test_the_balance_reads_as_text_on_the_balance_button(self):
        with mock.patch('urllib.request.urlopen', return_value=answer({'error': 0, 'msg': 'Success', 'data': {'balance': '57.2500'}})):
            self.assertEqual(services.gateway_balance(), 'balance: 57.2500')

    def test_a_bad_key_on_the_balance_check_says_so(self):
        with mock.patch('urllib.request.urlopen', return_value=answer({'error': 405, 'msg': 'Authorization required'})):
            with self.assertRaisesMessage(SmsError, 'Authorization required (code 405)'):
                services.gateway_balance()

    def test_the_screens_name_the_gateway(self):
        self.assertEqual(services.backend_description(), 'sms.net.bd - messages are really sent')


@override_settings(**NETBD)
class SmsNetBdEndToEndTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser('boss', 'b@example.com', 'pw')
        _, flats = make_project('Tower 1', floors=1, units=2)
        self.customer = Customer.objects.create(name='Rahim', phone='01711000001')
        self.account = make_account()
        self.sale = FlatSale.objects.create(flat=flats[0], customer=self.customer, sale_date='2026-03-05', sale_value=1200)

    def test_a_payment_sms_is_sent_and_the_request_id_logged(self):
        payment = CustomerPayment.objects.create(sale=self.sale, payment_date='2026-04-01', amount=500, account=self.account)
        with mock.patch('urllib.request.urlopen', return_value=answer(OK)):
            log = services.notify_payment(payment)
        self.assertEqual((log.status, log.gateway_id, log.kind), (SmsLog.Status.SENT, '4242', SmsLog.Kind.PAYMENT))

    def test_a_booking_sms_is_sent_the_same_way(self):
        with mock.patch('urllib.request.urlopen', return_value=answer(OK)) as opened:
            log = services.notify_booking(self.sale)
        self.assertEqual((log.status, log.kind), (SmsLog.Status.SENT, SmsLog.Kind.BOOKING))
        self.assertIn('Congratulations', parse_qs(opened.call_args.args[0].data.decode())['msg'][0])

    def test_a_refused_sms_is_logged_with_the_reason_and_never_blocks_the_payment(self):
        payment = CustomerPayment.objects.create(sale=self.sale, payment_date='2026-04-01', amount=500, account=self.account)
        with mock.patch('urllib.request.urlopen', return_value=answer({'error': 417, 'msg': 'Insufficient balance'})):
            log = services.notify_payment(payment)
        self.assertEqual((log.status, log.error), (SmsLog.Status.FAILED, 'Insufficient balance (code 417)'))
        self.assertTrue(CustomerPayment.objects.filter(pk=payment.pk).exists())

    def test_the_other_gateways_settings_are_left_alone(self):
        # switching to sms.net.bd must not need the ZendSMS key, and vice versa
        self.assertIsInstance(ZendSmsBackend(), ZendSmsBackend)
        with override_settings(SMS_BACKEND='zendsms', SMS_API_KEY='z-key', SMS_SENDER_ID='8809612781041', SMSNETBD_API_KEY=''):
            reply = answer({'success': True, 'data': {'message_id': 'z-1'}})
            with mock.patch('urllib.request.urlopen', return_value=reply):
                self.assertEqual(ZendSmsBackend().send('+8801711000001', 'hi'), 'z-1')


class TestsNeverReachTheRealGatewayTests(TestCase):
    def test_the_test_run_has_no_sms_net_bd_key(self):
        from django.conf import settings
        self.assertEqual((settings.SMS_BACKEND, settings.SMSNETBD_API_KEY), ('log', ''))
