from decimal import Decimal

from django.test import TestCase

from customers.models import Customer
from projects.models import Flat, Project

from .forms import CustomerPaymentForm, FlatSaleForm
from .models import CustomerPayment, FlatSale


class FlatStatusLifecycleTests(TestCase):
    def setUp(self):
        self.project = Project.objects.create(project_name='P', total_saleable_area=2000)
        self.flat = Flat.objects.create(
            project=self.project, flat_no='A1', floor_no=1, saleable_area=1000, base_price=1000,
        )
        self.customer = Customer.objects.create(name='C', phone='+8801700000001')

    def make_sale(self, flat=None, price=1000):
        return FlatSale.objects.create(
            flat=flat or self.flat, customer=self.customer, sale_date='2026-01-01', base_price=price,
        )

    def pay(self, sale, amount):
        return CustomerPayment.objects.create(
            sale=sale, payment_date='2026-01-02', amount=Decimal(amount),
        )

    def test_new_flat_is_available(self):
        self.assertEqual(self.flat.status, Flat.Status.AVAILABLE)

    def test_booking_makes_flat_booked(self):
        sale = self.make_sale()
        self.flat.refresh_from_db()
        self.assertEqual(sale.status, FlatSale.Status.BOOKED)
        self.assertEqual(self.flat.status, Flat.Status.BOOKED)

    def test_partial_payment_stays_booked(self):
        sale = self.make_sale()
        self.pay(sale, 400)
        sale.refresh_from_db()
        self.flat.refresh_from_db()
        self.assertEqual(sale.status, FlatSale.Status.BOOKED)
        self.assertEqual(self.flat.status, Flat.Status.BOOKED)

    def test_full_payment_makes_flat_sold(self):
        sale = self.make_sale()
        self.pay(sale, 400)
        self.pay(sale, 600)
        sale.refresh_from_db()
        self.flat.refresh_from_db()
        self.assertEqual(sale.status, FlatSale.Status.SOLD)
        self.assertEqual(self.flat.status, Flat.Status.SOLD)

    def test_removing_a_payment_reverts_to_booked(self):
        sale = self.make_sale()
        payment = self.pay(sale, 1000)
        payment.delete()
        sale.refresh_from_db()
        self.flat.refresh_from_db()
        self.assertEqual(sale.status, FlatSale.Status.BOOKED)
        self.assertEqual(self.flat.status, Flat.Status.BOOKED)

    def test_cancelling_frees_the_flat(self):
        sale = self.make_sale()
        sale.status = FlatSale.Status.CANCELLED
        sale.save()
        self.flat.refresh_from_db()
        self.assertEqual(self.flat.status, Flat.Status.AVAILABLE)

    def test_flat_status_is_not_editable(self):
        self.assertFalse(Flat._meta.get_field('status').editable)
        self.assertEqual([c[0] for c in Flat.Status.choices], ['AVAILABLE', 'BOOKED', 'SOLD'])


class FlatSaleFormTests(TestCase):
    def setUp(self):
        self.project = Project.objects.create(project_name='P', total_saleable_area=2000)
        self.free = Flat.objects.create(project=self.project, flat_no='A1', floor_no=1, saleable_area=1000, base_price=1000)
        self.taken = Flat.objects.create(project=self.project, flat_no='A2', floor_no=1, saleable_area=1000, base_price=1000)
        self.customer = Customer.objects.create(name='C', phone='+8801700000001')
        self.sale = FlatSale.objects.create(
            flat=self.taken, customer=self.customer, sale_date='2026-01-01', base_price=1000,
        )

    def data(self, flat, **extra):
        return {
            'flat': flat.pk, 'customer': self.customer.pk, 'sale_date': '2026-02-01',
            'base_price': '1000', 'other_charges': '0', 'discount': '0', **extra,
        }

    def test_only_available_flats_are_offered(self):
        choices = list(FlatSaleForm().fields['flat'].queryset)
        self.assertEqual(choices, [self.free])

    def test_cannot_pick_a_booked_flat(self):
        form = FlatSaleForm(data=self.data(self.taken))
        self.assertFalse(form.is_valid())
        self.assertIn('flat', form.errors)

    def test_can_sell_an_available_flat(self):
        form = FlatSaleForm(data=self.data(self.free))
        self.assertTrue(form.is_valid(), form.errors)
        sale = form.save()
        self.assertEqual(sale.status, FlatSale.Status.BOOKED)

    def test_flat_is_locked_when_editing(self):
        form = FlatSaleForm(instance=self.sale)
        self.assertTrue(form.fields['flat'].disabled)

    def test_cancel_checkbox_frees_flat_then_it_can_be_resold(self):
        form = FlatSaleForm(data=self.data(self.taken, cancel_sale='on'), instance=self.sale)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.taken.refresh_from_db()
        self.assertEqual(self.taken.status, Flat.Status.AVAILABLE)
        self.assertTrue(FlatSaleForm(data=self.data(self.taken)).is_valid())

    def test_payment_form_hides_cancelled_sales(self):
        self.sale.status = FlatSale.Status.CANCELLED
        self.sale.save()
        self.assertEqual(list(CustomerPaymentForm().fields['sale'].queryset), [])


class ReceiptPositionTests(TestCase):
    def setUp(self):
        project = Project.objects.create(project_name='P', total_saleable_area=1000)
        flat = Flat.objects.create(project=project, flat_no='A1', floor_no=1, saleable_area=1000, base_price=1000)
        customer = Customer.objects.create(name='C', phone='+8801700000001')
        self.sale = FlatSale.objects.create(flat=flat, customer=customer, sale_date='2026-01-01', base_price=1000)

    def context_for(self, payment):
        from django.test import RequestFactory
        from .views import CustomerPaymentReceiptView

        view = CustomerPaymentReceiptView()
        view.setup(RequestFactory().get('/'), pk=payment.pk)
        view.object = payment
        return view.get_context_data()

    def test_receipt_shows_position_as_of_that_payment(self):
        first = CustomerPayment.objects.create(sale=self.sale, payment_date='2026-02-01', amount=300)
        second = CustomerPayment.objects.create(sale=self.sale, payment_date='2026-03-01', amount=700)
        one = self.context_for(first)
        self.assertEqual((one['received_to_date'], one['balance_after']), (300, 700))
        two = self.context_for(second)
        self.assertEqual((two['received_to_date'], two['balance_after']), (1000, 0))

    def test_same_day_payments_are_ordered_by_entry(self):
        first = CustomerPayment.objects.create(sale=self.sale, payment_date='2026-02-01', amount=200)
        second = CustomerPayment.objects.create(sale=self.sale, payment_date='2026-02-01', amount=100)
        self.assertEqual(self.context_for(first)['received_to_date'], 200)
        self.assertEqual(self.context_for(second)['received_to_date'], 300)

    def test_document_numbers(self):
        payment = CustomerPayment.objects.create(sale=self.sale, payment_date='2026-02-01', amount=1)
        self.assertEqual(payment.receipt_no, f'MR-{payment.pk:05d}')
