from unittest import mock
from urllib.parse import parse_qs, unquote, urlparse

from django.contrib.auth.models import AnonymousUser, Permission, User
from django.contrib.messages import get_messages
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.test import RequestFactory, TestCase, override_settings

from core.testing import make_account, make_project, make_request
from customers.models import Customer
from sales.models import CustomerPayment, FlatSale
from sales.views import SharedInvoiceView

from . import whatsapp
from .models import WhatsAppShare
from .views import WhatsAppInvoicesView, WhatsAppSendView


@override_settings(ALLOWED_HOSTS=['erp.example.com', 'testserver'])
class WhatsAppTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser('boss', 'b@example.com', 'pw')
        self.project, self.flats = make_project('Tower 1', floors=1, units=4)
        self.account = make_account()
        self.with_wa = Customer.objects.create(title='MR', name='Rahim', phone='01711000001', whatsapp_no='01711000009')
        self.without_wa = Customer.objects.create(name='Karim', phone='01711000002')
        self.sale = self.sell(self.flats[0], self.with_wa)
        self.sale2 = self.sell(self.flats[1], self.without_wa)

    def sell(self, flat, customer, value=1200):
        return FlatSale.objects.create(flat=flat, customer=customer, sale_date='2026-01-01', sale_value=value)

    def request(self, path='/', method='get', data=None, user=None):
        request = make_request(user or self.user, path, method, data)
        request.META['HTTP_HOST'] = 'erp.example.com'
        return request


class LinkTokenTests(WhatsAppTestCase):
    def test_the_token_leads_back_to_the_sale(self):
        self.assertEqual(whatsapp.sale_pk_from_token(whatsapp.invoice_token(self.sale)), self.sale.pk)

    def test_a_tampered_token_is_refused(self):
        token = whatsapp.invoice_token(self.sale)
        self.assertIsNone(whatsapp.sale_pk_from_token(token[:-2] + 'xx'))
        self.assertIsNone(whatsapp.sale_pk_from_token('garbage'))

    def test_a_token_for_another_sale_cannot_be_forged_by_changing_the_id(self):
        import base64
        token = whatsapp.invoice_token(self.sale)
        forged = base64.urlsafe_b64encode(str(self.sale2.pk).encode()).decode().rstrip('=') + ':' + token.split(':', 1)[1]
        self.assertIsNone(whatsapp.sale_pk_from_token(forged))

    def test_a_token_expires_after_30_days(self):
        import time
        token = whatsapp.invoice_token(self.sale)
        with mock.patch('time.time', return_value=time.time() + 29 * 86400):
            self.assertEqual(whatsapp.sale_pk_from_token(token), self.sale.pk)
        with mock.patch('time.time', return_value=time.time() + 31 * 86400):
            self.assertIsNone(whatsapp.sale_pk_from_token(token))

    def test_a_token_made_for_something_else_does_not_work(self):
        from django.core import signing
        self.assertIsNone(whatsapp.sale_pk_from_token(signing.dumps(self.sale.pk, salt='other-purpose')))


class NumberAndMessageTests(WhatsAppTestCase):
    def test_digits_only_for_wa_me(self):
        self.assertEqual(whatsapp.whatsapp_digits('+8801711000009'), '8801711000009')
        self.assertEqual(whatsapp.whatsapp_digits('+88 01711-000009'), '8801711000009')
        self.assertEqual(whatsapp.whatsapp_digits(''), '')

    def test_who_counts_as_having_whatsapp(self):
        self.assertTrue(whatsapp.has_whatsapp(self.with_wa))
        self.assertFalse(whatsapp.has_whatsapp(self.without_wa))
        self.assertFalse(whatsapp.has_whatsapp(Customer(whatsapp_no='123')))   # too short to be a real number

    def test_the_message_names_the_invoice_flat_and_amounts(self):
        text = whatsapp.invoice_message(self.sale, 'https://erp.example.com/x/')
        for expected in ('Mr. Rahim', self.sale.sale_no, 'A1', 'Tower 1', 'Tk 1,200.00', 'balance due Tk 1,200.00', 'https://erp.example.com/x/'):
            self.assertIn(expected, text)

    def test_a_paid_sale_has_no_balance_due_line(self):
        CustomerPayment.objects.create(sale=self.sale, payment_date='2026-02-01', amount=1200, account=self.account)
        self.sale.refresh_from_db()
        self.assertNotIn('balance due', whatsapp.invoice_message(self.sale, 'https://x/'))

    def test_the_message_never_contains_the_base_price_or_honorarium(self):
        sale = self.sell(self.flats[2], self.with_wa, value=1500)   # honorarium 500 over the 1000 base price
        text = whatsapp.invoice_message(sale, 'https://x/')
        self.assertNotIn('1,000.00', text)
        self.assertNotIn('onorarium', text)

    def test_the_link_is_url_encoded(self):
        link = whatsapp.whatsapp_link('+8801711000009', 'Hi there & thanks: 100%')
        self.assertTrue(link.startswith('https://wa.me/8801711000009?text='))
        self.assertEqual(unquote(link.split('?text=')[1]), 'Hi there & thanks: 100%')


class SendListTests(WhatsAppTestCase):
    def context(self, **params):
        view = WhatsAppInvoicesView()
        view.setup(self.request(data=params))
        return view.get_context_data()

    def test_only_customers_with_a_whatsapp_number_are_ready(self):
        context = self.context()
        self.assertEqual([s.customer for s in context['ready']], [self.with_wa])
        self.assertEqual([s.customer for s in context['missing']], [self.without_wa])

    def test_cancelled_sales_are_left_out_entirely(self):
        self.sale.cancel(100)
        self.sale.save()
        context = self.context()
        self.assertEqual(context['ready'], [])
        self.assertNotIn(self.sale, context['missing'])

    def test_it_can_be_limited_to_one_project(self):
        other, other_flats = make_project('Tower 2', floors=1, units=1)
        self.sell(other_flats[0], self.with_wa)
        self.assertEqual(len(self.context()['ready']), 2)
        ready = self.context(project=other.pk)['ready']
        self.assertEqual([s.project for s in ready], [other])

    def test_it_shows_when_each_invoice_was_last_opened(self):
        WhatsAppShare.objects.create(sale=self.sale, customer=self.with_wa, phone='+8801711000009')
        self.assertIsNotNone(self.context()['ready'][0].last_share)

    def test_a_bad_project_id_is_ignored(self):
        self.assertEqual(len(self.context(project='abc')['ready']), 1)

    def test_it_needs_the_permission(self):
        clerk = User.objects.create_user('clerk')
        with self.assertRaises(PermissionDenied):
            WhatsAppInvoicesView.as_view()(self.request(user=clerk))

    def test_the_page_renders_with_the_buttons(self):
        response = WhatsAppInvoicesView.as_view()(self.request())
        response.render()
        html = response.content.decode()
        self.assertIn(f'/sms/whatsapp/{self.sale.pk}/send/', html)
        self.assertNotIn(f'/sms/whatsapp/{self.sale2.pk}/send/', html)   # no number: no button, an "Add WhatsApp no." link
        self.assertIn('Add WhatsApp no.', html)


class SendTests(WhatsAppTestCase):
    def send(self, sale, user=None, **data):
        request = self.request('/sms/whatsapp/1/send/', 'post', data, user)
        response = WhatsAppSendView.as_view()(request, pk=sale.pk)
        return response, [str(m) for m in get_messages(request)]

    def test_it_opens_whatsapp_with_the_customers_number_and_the_invoice_link(self):
        response, _ = self.send(self.sale)
        self.assertEqual(response.status_code, 302)
        target = urlparse(response['Location'])
        self.assertEqual((target.netloc, target.path), ('wa.me', '/8801711000009'))
        text = parse_qs(target.query)['text'][0]
        self.assertIn(self.sale.sale_no, text)
        link = [word for word in text.split() if word.startswith('http://erp.example.com/sales/invoice/shared/')][0]
        token = link.rstrip('/').rsplit('/', 1)[1]
        self.assertEqual(whatsapp.sale_pk_from_token(token), self.sale.pk)

    def test_the_link_in_the_message_really_opens_the_invoice(self):
        response, _ = self.send(self.sale)
        text = parse_qs(urlparse(response['Location']).query)['text'][0]
        token = [w for w in text.split() if '/invoice/shared/' in w][0].rstrip('/').rsplit('/', 1)[1]
        page = SharedInvoiceView.as_view()(RequestFactory().get('/'), token=token)
        page.render()
        self.assertIn(self.sale.sale_no, page.content.decode())

    @override_settings(SITE_URL='https://erp.asgroupbd.com/')
    def test_site_url_decides_the_address_in_the_link(self):
        response, _ = self.send(self.sale)
        text = parse_qs(urlparse(response['Location']).query)['text'][0]
        link = [w for w in text.split() if '/invoice/shared/' in w][0]
        self.assertTrue(link.startswith('https://erp.asgroupbd.com/sales/invoice/shared/'), link)
        self.assertNotIn('//sales', link)

    def test_each_send_is_recorded(self):
        self.send(self.sale)
        self.send(self.sale)
        shares = WhatsAppShare.objects.all()
        self.assertEqual(shares.count(), 2)
        self.assertEqual((shares[0].sale, shares[0].customer, shares[0].phone, shares[0].opened_by),
                         (self.sale, self.with_wa, '+8801711000009', self.user))

    def test_a_customer_without_whatsapp_is_refused_with_an_explanation(self):
        response, messages_ = self.send(self.sale2)
        self.assertEqual(response.status_code, 302)
        self.assertNotIn('wa.me', response['Location'])
        self.assertIn('no WhatsApp number', messages_[0])
        self.assertEqual(WhatsAppShare.objects.count(), 0)

    def test_a_cancelled_sale_has_no_invoice_to_send(self):
        self.sale.cancel(100)
        self.sale.save()
        response, messages_ = self.send(self.sale)
        self.assertNotIn('wa.me', response['Location'])
        self.assertIn('cancelled', messages_[0])

    def test_it_returns_to_the_page_it_came_from_on_a_refusal(self):
        response, _ = self.send(self.sale2, next='/sales/5/')
        self.assertEqual(response['Location'], '/sales/5/')
        response, _ = self.send(self.sale2, next='https://evil.example.com/')
        self.assertEqual(response['Location'], '/sms/whatsapp/')

    def test_it_needs_the_permission(self):
        clerk = User.objects.create_user('clerk')
        with self.assertRaises(PermissionDenied):
            self.send(self.sale, user=clerk)
        clerk.user_permissions.add(Permission.objects.get(codename='add_whatsappshare'))
        response, _ = self.send(self.sale, user=User.objects.get(pk=clerk.pk))
        self.assertIn('wa.me', response['Location'])

    def test_a_get_request_does_nothing(self):
        request = self.request('/', 'get')
        self.assertEqual(WhatsAppSendView.as_view()(request, pk=self.sale.pk).status_code, 405)


class SharedInvoiceTests(WhatsAppTestCase):
    def open(self, token, user=None):
        request = RequestFactory().get('/')
        request.user = user or AnonymousUser()
        return SharedInvoiceView.as_view()(request, token=token)

    def test_it_opens_without_logging_in(self):
        response = self.open(whatsapp.invoice_token(self.sale))
        response.render()
        html = response.content.decode()
        self.assertEqual(response.status_code, 200)
        self.assertIn('INVOICE', html)
        self.assertIn(self.sale.sale_no, html)
        self.assertIn('Rahim', html)

    def test_it_is_the_customer_facing_invoice_only(self):
        sale = self.sell(self.flats[2], self.with_wa, value=1500)   # base price 1000, honorarium 500
        html = self.render(whatsapp.invoice_token(sale))
        for hidden in ('Base price', 'Honorarium', 'base price', '1,000.00', 'Total base'):
            self.assertNotIn(hidden, html)
        self.assertIn('1,500.00', html)

    def render(self, token):
        response = self.open(token)
        response.render()
        return response.content.decode()

    def test_it_has_no_link_back_into_the_system(self):
        html = self.render(whatsapp.invoice_token(self.sale))
        self.assertNotIn('/sales/%d/' % self.sale.pk, html)
        self.assertNotIn('Back', html)
        self.assertNotIn('Printed by', html)

    def test_a_bad_or_expired_link_is_a_404(self):
        for bad in ('nonsense', whatsapp.invoice_token(self.sale)[:-3] + 'abc'):
            with self.assertRaises(Http404):
                self.open(bad)

    def test_it_is_not_cached_or_indexed(self):
        response = self.open(whatsapp.invoice_token(self.sale))
        self.assertIn('noindex', response['X-Robots-Tag'])
        self.assertIn('no-store', response['Cache-Control'])

    def test_a_link_for_a_deleted_sale_is_a_404(self):
        token = whatsapp.invoice_token(self.sale)
        self.sale.delete()
        with self.assertRaises(Http404):
            self.open(token)

    def test_the_normal_invoice_still_needs_a_login(self):
        from sales.views import FlatSaleInvoiceView
        request = RequestFactory().get('/')
        request.user = AnonymousUser()
        self.assertEqual(FlatSaleInvoiceView.as_view()(request, pk=self.sale.pk).status_code, 302)

    def test_the_normal_invoice_keeps_its_back_button(self):
        from sales.views import FlatSaleInvoiceView
        response = FlatSaleInvoiceView.as_view()(self.request(), pk=self.sale.pk)
        response.render()
        self.assertIn('Back', response.content.decode())


class PaidInFullStampTests(WhatsAppTestCase):
    """Sold no longer means paid, so the stamp has to look at what has actually been received."""

    def invoice(self, sale):
        from sales.views import FlatSaleInvoiceView
        response = FlatSaleInvoiceView.as_view()(self.request(), pk=sale.pk)
        response.render()
        return response.content.decode()

    def test_an_unpaid_sale_is_not_stamped(self):
        self.assertNotIn('PAID IN FULL', self.invoice(self.sale))

    def test_a_partly_paid_sale_is_not_stamped(self):
        CustomerPayment.objects.create(sale=self.sale, payment_date='2026-02-01', amount=600, account=self.account)
        self.assertNotIn('PAID IN FULL', self.invoice(self.sale))

    def test_a_fully_paid_sale_is_stamped(self):
        CustomerPayment.objects.create(sale=self.sale, payment_date='2026-02-01', amount=1200, account=self.account)
        self.assertIn('PAID IN FULL', self.invoice(self.sale))

    def test_a_cancelled_sale_is_stamped_cancelled(self):
        self.sale.cancel(100)
        self.sale.save()
        html = self.invoice(self.sale)
        self.assertIn('CANCELLED', html)
        self.assertNotIn('PAID IN FULL', html)

    def test_the_sale_page_offers_whatsapp_only_where_there_is_a_number(self):
        from sales.views import FlatSaleDetailView
        for sale, expected, absent in ((self.sale, 'Send on WhatsApp', 'No WhatsApp no.'), (self.sale2, 'No WhatsApp no.', 'Send on WhatsApp')):
            response = FlatSaleDetailView.as_view()(self.request(), pk=sale.pk)
            response.render()
            html = response.content.decode()
            self.assertIn(expected, html)
            self.assertNotIn(absent, html)
