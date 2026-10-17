"""Money figures must stay off the screens shown to buyers while the sensitive screens are locked."""
import time

from django.contrib.auth.models import User
from django.contrib.messages import get_messages
from django.test import TestCase, override_settings

from core.testing import make_account, make_project, make_request
from costing.models import CostCategory, ProjectCost
from customers.models import Customer
from dashboard.views import HomeView
from projects.views import FlatDetailView, FlatListView, ProjectDetailView, ProjectListView
from sales.models import CustomerPayment, FlatSale, Reference
from sales.views import (
    CustomerPaymentCreateView,
    CustomerPaymentListView,
    FlatSaleCreateView,
    FlatSaleDetailView,
    FlatSaleListView,
    ReferenceDetailView,
)
from customers.views import CustomerDetailView

UNLOCKED = dict(session={'reauth_until': time.time() + 600, 'reauth_token': 'tok'}, cookies={'daj_unlocked': 'tok'})


class LockedScreenTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser('boss', 'b@example.com', 'pw')
        self.project, self.flats = make_project('Tower', base=13_500_123, quoted=15_100_000, parking=500_000)
        self.customer = Customer.objects.create(name='Rahim', phone='01711111111')
        self.ref = Reference.objects.create(name='Ref')
        self.account = make_account()
        self.sale = FlatSale.objects.create(
            flat=self.flats[0], customer=self.customer, sale_date='2026-01-01', sale_value=15_300_000, ref=self.ref,
        )
        CustomerPayment.objects.create(sale=self.sale, payment_date='2026-01-02', amount=2_222_222, account=self.account)
        ProjectCost.objects.create(
            project=self.project, cost_category=CostCategory.objects.create(name='Civil'), date='2026-01-03',
            amount=4_444_444, account=self.account,
        )

    def page(self, view, locked=True, path='/', **kwargs):
        extra = {} if locked else UNLOCKED
        response = view.as_view()(make_request(self.user, path, **extra), **kwargs)
        response.render()
        return response.content.decode()

    def check(self, view, hidden, shown, **kwargs):
        locked, unlocked = self.page(view, True, **kwargs), self.page(view, False, **kwargs)
        for text in hidden:
            self.assertNotIn(text, locked, f'{view.__name__} leaks {text!r} while locked')
            self.assertIn(text, unlocked, f'{view.__name__} should show {text!r} once unlocked')
        for text in shown:
            self.assertIn(text, locked, f'{view.__name__} lost {text!r}')

    def test_dashboard_hides_sale_value_received_receivable_and_costs(self):
        self.check(HomeView, ['15,300,000.00', '2,222,222.00', '4,444,444.00'], ['Quick Stats', 'Cost at a glance'])

    def test_dashboard_says_how_to_unlock(self):
        self.assertIn('Enter your password to show them', self.page(HomeView))

    def test_project_page_hides_sales_and_cost_cards(self):
        self.check(ProjectDetailView, ['Sales Value', '13,500,123.00', '4,444,444.00', '2,222,222.00'], ['Booking map', 'A1'], pk=self.project.pk)

    def test_project_list_hides_the_budget(self):
        self.project.budget_amount = 5_000_000
        self.project.save()
        self.check(ProjectListView, ['5,000,000.00'], ['Tower'])

    def test_flat_list_hides_paid_and_balance(self):
        self.check(FlatListView, ['2,222,222.00', '13,077,778.00'], ['A1', 'Rahim'])

    def test_flat_page_hides_prices_sale_figures_and_costs(self):
        self.check(FlatDetailView, ['13,500,123.00', '15,300,000.00', '2,222,222.00', '1,111,111.00'], ['Rahim'], pk=self.flats[0].pk)

    def test_sale_list_hides_every_amount(self):
        self.check(FlatSaleListView, ['15,300,000.00', '2,222,222.00', '13,077,778.00'], [self.sale.sale_no])

    def test_sale_page_hides_breakdown_honorarium_and_payment_amounts(self):
        self.check(FlatSaleDetailView, ['Sale Breakdown', '15,300,000.00', '2,222,222.00', 'Honorarium to'], [self.sale.sale_no], pk=self.sale.pk)

    def test_payment_list_hides_amounts(self):
        self.check(CustomerPaymentListView, ['2,222,222.00'], ['Rahim'])

    def test_customer_page_hides_receivable(self):
        self.check(CustomerDetailView, ['13,077,778.00', '2,222,222.00'], ['Rahim'], pk=self.customer.pk)

    def test_reference_page_hides_honorarium(self):
        self.sale.sale_value = 15_900_000
        self.sale.save()
        self.check(ReferenceDetailView, ['2,399,877.00'], ['Ref'], pk=self.ref.pk)

    def test_the_booking_form_keeps_the_base_price_out_of_the_page_while_locked(self):
        locked, unlocked = self.page(FlatSaleCreateView, True), self.page(FlatSaleCreateView, False)
        self.assertNotIn('13500123', locked)
        self.assertNotIn('Honorarium', locked)
        self.assertNotIn('Base price', locked)
        self.assertIn('13500123', unlocked)
        self.assertIn('Honorarium', unlocked)
        self.assertIn('15100000', locked)  # the quoted price is what the buyer is told anyway

    @override_settings(SENSITIVE_NAMESPACES=[])
    def test_nothing_is_hidden_when_no_screens_are_guarded(self):
        self.assertIn('15,300,000.00', self.page(HomeView))

    def test_closing_the_browser_hides_the_figures_again(self):
        # session still inside its window, but the browser dropped the unlock cookie
        request = make_request(self.user, '/', session=UNLOCKED['session'], cookies={})
        response = HomeView.as_view()(request)
        response.render()
        self.assertNotIn('15,300,000.00', response.content.decode())


class PaymentSmsMessageTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser('boss', 'b@example.com', 'pw')
        _, flats = make_project()
        self.customer = Customer.objects.create(name='Rahim', phone='01711111111')
        self.sale = FlatSale.objects.create(flat=flats[0], customer=self.customer, sale_date='2026-01-01', sale_value=1200)
        self.account = make_account()

    def pay(self):
        data = {'sale': self.sale.pk, 'payment_date': '2026-02-01', 'amount': '500', 'account': self.account.pk}
        request = make_request(self.user, '/', 'post', data)
        CustomerPaymentCreateView.as_view()(request)
        return [str(m) for m in get_messages(request)]

    def test_it_says_plainly_when_the_sms_was_only_logged(self):
        text = ' '.join(self.pay())
        self.assertIn('NOT delivered', text)
        self.assertIn('+8801711111111', text)

    def test_it_confirms_a_delivered_sms(self):
        from unittest import mock

        class Gateway:
            name = 'http'
            delivers = True

            def send(self, phone, message, reference=''):
                return 'ok'

        with mock.patch('sms.services.get_backend', return_value=Gateway()):
            text = ' '.join(self.pay())
        self.assertIn('Payment SMS sent to +8801711111111', text)
        self.assertNotIn('NOT', text)

    def test_it_says_when_the_customer_is_excluded(self):
        self.customer.sms_enabled = False
        self.customer.save()
        self.assertIn('excluded from SMS', ' '.join(self.pay()))
