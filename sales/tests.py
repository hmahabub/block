from decimal import Decimal

from django.contrib.auth.models import User
from django.test import RequestFactory, TestCase

from books.models import Account
from core.testing import make_account, make_project, make_request
from customers.models import Customer
from projects.models import Flat

from .forms import (
    CustomerPaymentForm,
    FlatSaleForm,
    HonorariumPaymentForm,
    RefundPaymentForm,
    SaleCancelForm,
)
from .models import CustomerPayment, FlatSale, HonorariumPayment, RefundPayment, Reference
from .views import (
    CustomerPaymentCreateView,
    CustomerPaymentReceiptView,
    FlatSaleCancelView,
)

D = Decimal


class SaleTestCase(TestCase):
    """Project: base price 1000, quoted 1200, parking 100. Flats A1, B1, A2, B2."""

    def setUp(self):
        self.project, self.flats = make_project()
        self.flat = self.flats[0]
        self.customer = Customer.objects.create(name='C', phone='01700000001')
        self.account = make_account()
        self.ref = Reference.objects.create(name='Ref')

    def make_sale(self, flat=None, sale_value=1200, reg_value=0, parking=False, **extra):
        return FlatSale.objects.create(
            flat=flat or self.flat, customer=self.customer, sale_date='2026-01-01', with_parking=parking,
            sale_value=sale_value, reg_value=reg_value, **extra,
        )

    def pay(self, sale, amount, date='2026-01-02'):
        return CustomerPayment.objects.create(sale=sale, payment_date=date, amount=D(amount), account=self.account)


class SaleMoneyTests(SaleTestCase):
    def test_prices_are_frozen_from_the_project_at_booking(self):
        sale = self.make_sale()
        self.project.base_price = 5000
        self.project.save()
        sale.refresh_from_db()
        self.assertEqual((sale.base_price, sale.parking_price), (1000, 0))

    def test_honorarium_is_sale_value_less_total_base_price(self):
        sale = self.make_sale(sale_value=1500)
        self.assertEqual((sale.total_base_price, sale.honorarium), (1000, 500))

    def test_parking_price_is_added_to_the_base_amount(self):
        sale = self.make_sale(sale_value=1500, parking=True)
        self.assertEqual((sale.parking_price, sale.total_base_price, sale.honorarium), (100, 1100, 400))

    def test_net_value_adds_the_registration_value(self):
        sale = self.make_sale(sale_value=1200, reg_value=300)
        self.assertEqual((sale.net_value, sale.receivable_amount), (1500, 1500))

    def test_a_new_sale_is_sold_and_so_is_its_flat(self):
        sale = self.make_sale()
        self.flat.refresh_from_db()
        self.assertEqual((sale.status, self.flat.status), (FlatSale.Status.SOLD, Flat.Status.SOLD))

    def test_a_sale_is_sold_whether_or_not_it_has_been_paid_for(self):
        sale = self.make_sale(sale_value=1200, reg_value=300)
        self.assertEqual(sale.status, FlatSale.Status.SOLD)
        self.pay(sale, 600)
        sale.refresh_from_db()
        self.flat.refresh_from_db()
        self.assertEqual((sale.status, self.flat.status), (FlatSale.Status.SOLD, Flat.Status.SOLD))
        self.assertEqual(sale.receivable_amount, 900)  # what is still to be collected is tracked separately
        self.pay(sale, 900)
        sale.refresh_from_db()
        self.assertEqual((sale.status, sale.receivable_amount), (FlatSale.Status.SOLD, 0))

    def test_paying_more_than_the_net_value_becomes_customer_balance(self):
        sale = self.make_sale(sale_value=1200, reg_value=100)
        self.pay(sale, 1500)
        sale.refresh_from_db()
        self.assertEqual((sale.receivable_amount, sale.customer_balance), (0, 200))
        self.assertEqual(sale.status, FlatSale.Status.SOLD)

    def test_removing_a_payment_does_not_unsell_the_flat(self):
        sale = self.make_sale()
        payment = self.pay(sale, 1200)
        payment.delete()
        sale.refresh_from_db()
        self.flat.refresh_from_db()
        self.assertEqual((sale.status, self.flat.status), (FlatSale.Status.SOLD, Flat.Status.SOLD))
        self.assertEqual(sale.receivable_amount, 1200)

    def test_flat_status_is_not_editable(self):
        self.assertFalse(Flat._meta.get_field('status').editable)
        self.assertEqual([c[0] for c in Flat.Status.choices], ['AVAILABLE', 'SOLD'])
        self.assertEqual([c[0] for c in FlatSale.Status.choices], ['SOLD', 'CANCELLED'])

    def test_payment_method_follows_the_account(self):
        cash = make_account('Petty cash', account_type=Account.AccountType.CASH)
        sale = self.make_sale()
        bank_payment = self.pay(sale, 100)
        cash_payment = CustomerPayment.objects.create(sale=sale, payment_date='2026-01-03', amount=50, account=cash)
        self.assertEqual((bank_payment.payment_method, cash_payment.payment_method), ('BANK', 'CASH'))


class CancellationTests(SaleTestCase):
    def cancel(self, sale, percent):
        sale.cancel(percent)
        sale.save()
        sale.refresh_from_db()

    def test_cancelling_frees_the_flat(self):
        sale = self.make_sale()
        self.cancel(sale, 100)
        self.flat.refresh_from_db()
        self.assertEqual(self.flat.status, Flat.Status.AVAILABLE)
        self.assertEqual(sale.status, FlatSale.Status.CANCELLED)

    def test_refund_is_a_percentage_of_everything_received(self):
        sale = self.make_sale()
        self.pay(sale, 800)
        self.cancel(sale, 75)
        self.assertEqual((sale.refund_percent, sale.refund_amount, sale.retained_on_cancellation), (75, 600, 200))

    def test_refund_can_be_the_full_amount(self):
        sale = self.make_sale()
        self.pay(sale, 800)
        self.cancel(sale, 100)
        self.assertEqual((sale.refund_amount, sale.retained_on_cancellation), (800, 0))

    def test_refund_payments_cannot_exceed_what_is_due(self):
        sale = self.make_sale()
        self.pay(sale, 800)
        self.cancel(sale, 50)
        form = RefundPaymentForm(data={'date': '2026-02-01', 'amount': '500', 'account': self.account.pk}, sale=sale)
        self.assertFalse(form.is_valid())
        self.assertIn('amount', form.errors)
        ok = RefundPaymentForm(data={'date': '2026-02-01', 'amount': '400', 'account': self.account.pk}, sale=sale)
        self.assertTrue(ok.is_valid(), ok.errors)
        ok.save()
        sale.refresh_from_db()
        self.assertEqual((sale.refund_paid, sale.refund_due), (400, 0))

    def test_a_cancelled_sale_owes_no_honorarium(self):
        sale = self.make_sale(sale_value=1500, ref=self.ref)
        self.cancel(sale, 100)
        self.assertEqual(sale.honorarium_due, 0)

    def test_cancel_form_limits_the_percentage(self):
        self.assertFalse(SaleCancelForm(data={'refund_percent': '101', 'cancelled_on': '2026-02-01'}).is_valid())
        self.assertFalse(SaleCancelForm(data={'refund_percent': '-1', 'cancelled_on': '2026-02-01'}).is_valid())
        self.assertTrue(SaleCancelForm(data={'refund_percent': '0', 'cancelled_on': '2026-02-01'}).is_valid())

    def test_cancel_view_records_the_refund_terms(self):
        sale = self.make_sale()
        self.pay(sale, 1000)
        user = User.objects.create_superuser('boss', 'b@example.com', 'pw')
        request = make_request(user, f'/sales/{sale.pk}/cancel/', 'post', {'refund_percent': '80', 'cancelled_on': '2026-03-01'})
        response = FlatSaleCancelView.as_view()(request, pk=sale.pk)
        self.assertEqual(response.status_code, 302)
        sale.refresh_from_db()
        self.assertEqual((sale.status, sale.refund_amount, str(sale.cancelled_on)), ('CANCELLED', 800, '2026-03-01'))

    def test_the_flat_can_be_sold_again_after_cancelling(self):
        sale = self.make_sale()
        self.cancel(sale, 100)
        again = self.make_sale()
        self.assertEqual(again.status, FlatSale.Status.SOLD)


class FlatSaleFormTests(SaleTestCase):
    def data(self, flat, **extra):
        return {
            'flat': flat.pk, 'customer': self.customer.pk, 'sale_date': '2026-02-01',
            'sale_value': '1200', 'reg_value': '0', **extra,
        }

    def test_only_available_flats_are_offered(self):
        taken = self.make_sale(self.flats[1])
        offered = list(FlatSaleForm().fields['flat'].queryset)
        self.assertNotIn(taken.flat, offered)
        self.assertIn(self.flat, offered)

    def test_cannot_pick_a_flat_that_is_already_sold(self):
        taken = self.make_sale(self.flats[1])
        form = FlatSaleForm(data=self.data(taken.flat))
        self.assertFalse(form.is_valid())
        self.assertIn('flat', form.errors)

    def test_can_sell_an_available_flat(self):
        form = FlatSaleForm(data=self.data(self.flat, ref=self.ref.pk))
        self.assertTrue(form.is_valid(), form.errors)
        sale = form.save()
        self.assertEqual((sale.status, sale.ref), (FlatSale.Status.SOLD, self.ref))

    def test_sale_value_cannot_be_below_the_base_price(self):
        form = FlatSaleForm(data=self.data(self.flat, sale_value='999'))
        self.assertFalse(form.is_valid())
        self.assertIn('sale_value', form.errors)

    def test_taking_parking_raises_the_minimum_sale_value(self):
        self.assertTrue(FlatSaleForm(data=self.data(self.flat, sale_value='1050')).is_valid())
        dearer = FlatSaleForm(data=self.data(self.flat, sale_value='1050', with_parking='on'))
        self.assertFalse(dearer.is_valid())
        self.assertIn('sale_value', dearer.errors)

    def test_ref_is_optional(self):
        self.assertTrue(FlatSaleForm(data=self.data(self.flat)).is_valid())

    def test_flat_is_locked_when_editing(self):
        sale = self.make_sale()
        self.assertTrue(FlatSaleForm(instance=sale).fields['flat'].disabled)

    def test_price_map_feeds_the_live_preview(self):
        prices = FlatSaleForm().price_map()[self.flat.pk]
        self.assertEqual((prices['base'], prices['quoted'], prices['parking']), ('1000.00', '1200.00', '100.00'))

    def test_payment_form_hides_cancelled_sales(self):
        sale = self.make_sale()
        sale.cancel(100)
        sale.save()
        self.assertNotIn(sale, list(CustomerPaymentForm().fields['sale'].queryset))

    def test_payment_form_requires_an_account(self):
        sale = self.make_sale()
        form = CustomerPaymentForm(data={'sale': sale.pk, 'payment_date': '2026-02-01', 'amount': '10'})
        self.assertFalse(form.is_valid())
        self.assertIn('account', form.errors)


class HonorariumTests(SaleTestCase):
    def test_honorarium_payments_are_limited_to_what_is_due(self):
        sale = self.make_sale(sale_value=1500, ref=self.ref)
        base = {'date': '2026-02-01', 'account': self.account.pk}
        self.assertFalse(HonorariumPaymentForm(data={**base, 'amount': '501'}, sale=sale).is_valid())
        form = HonorariumPaymentForm(data={**base, 'amount': '300'}, sale=sale)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        sale.refresh_from_db()
        self.assertEqual((sale.honorarium_paid, sale.honorarium_due), (300, 200))
        self.assertFalse(HonorariumPaymentForm(data={**base, 'amount': '201'}, sale=sale).is_valid())

    def test_sale_without_honorarium_has_nothing_to_pay(self):
        sale = self.make_sale(sale_value=1000)
        self.assertEqual(sale.honorarium_due, 0)

    def test_payout_references_are_numbered(self):
        sale = self.make_sale(sale_value=1500, ref=self.ref)
        hp = HonorariumPayment.objects.create(sale=sale, date='2026-02-01', amount=10, account=self.account)
        sale.cancel(100)
        sale.save()
        rf = RefundPayment.objects.create(sale=sale, date='2026-02-02', amount=10, account=self.account)
        self.assertEqual((hp.reference_no, rf.reference_no), (f'HP-{hp.pk:05d}', f'RF-{rf.pk:05d}'))


class PaymentViewTests(SaleTestCase):
    def post_payment(self, sale, amount='500', **extra):
        user = User.objects.create_superuser(f'u{User.objects.count()}', 'u@example.com', 'pw')
        data = {'sale': sale.pk, 'payment_date': '2026-02-01', 'amount': amount, 'account': self.account.pk, **extra}
        return CustomerPaymentCreateView.as_view()(make_request(user, '/sales/payments/create/', 'post', data))

    def test_payment_is_recorded_and_the_customer_gets_an_sms(self):
        from sms.models import SmsLog
        sale = self.make_sale()
        self.assertEqual(self.post_payment(sale).status_code, 302)
        payment = CustomerPayment.objects.get()
        self.assertEqual((payment.customer, payment.account), (self.customer, self.account))
        log = SmsLog.objects.get()
        self.assertEqual((log.kind, log.customer, log.phone), (SmsLog.Kind.PAYMENT, self.customer, '+8801700000001'))
        self.assertIn(payment.receipt_no, log.message)

    def test_an_excluded_customer_gets_no_sms_but_the_payment_still_saves(self):
        from sms.models import SmsLog
        self.customer.sms_enabled = False
        self.customer.save()
        self.post_payment(self.make_sale())
        self.assertEqual(CustomerPayment.objects.count(), 1)
        self.assertEqual(SmsLog.objects.count(), 0)


class ReceiptPositionTests(SaleTestCase):
    def setUp(self):
        super().setUp()
        self.sale = self.make_sale(sale_value=1000)

    def context_for(self, payment):
        view = CustomerPaymentReceiptView()
        view.setup(RequestFactory().get('/'), pk=payment.pk)
        view.object = payment
        return view.get_context_data()

    def test_receipt_shows_position_as_of_that_payment(self):
        first = CustomerPayment.objects.create(sale=self.sale, payment_date='2026-02-01', amount=300, account=self.account)
        second = CustomerPayment.objects.create(sale=self.sale, payment_date='2026-03-01', amount=700, account=self.account)
        one = self.context_for(first)
        self.assertEqual((one['received_to_date'], one['balance_after']), (300, 700))
        two = self.context_for(second)
        self.assertEqual((two['received_to_date'], two['balance_after']), (1000, 0))

    def test_receipt_shows_credit_when_overpaid(self):
        payment = CustomerPayment.objects.create(sale=self.sale, payment_date='2026-02-01', amount=1250, account=self.account)
        context = self.context_for(payment)
        self.assertEqual((context['balance_after'], context['credit_after']), (0, 250))

    def test_same_day_payments_are_ordered_by_entry(self):
        first = CustomerPayment.objects.create(sale=self.sale, payment_date='2026-02-01', amount=200, account=self.account)
        second = CustomerPayment.objects.create(sale=self.sale, payment_date='2026-02-01', amount=100, account=self.account)
        self.assertEqual(self.context_for(first)['received_to_date'], 200)
        self.assertEqual(self.context_for(second)['received_to_date'], 300)

    def test_document_numbers(self):
        payment = CustomerPayment.objects.create(sale=self.sale, payment_date='2026-02-01', amount=1, account=self.account)
        self.assertEqual(payment.receipt_no, f'MR-{payment.pk:05d}')
