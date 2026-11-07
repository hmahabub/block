"""The flat and the parking lot each have their own sale value, and the whole calculation is shown."""
import re
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from core.testing import enter_project, make_project, unlock_client
from customers.models import Customer
from projects.models import Development

from .forms import FlatSaleForm
from .models import FlatSale

D = Decimal


class ParkingSaleValueTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser('boss', 'b@example.com', 'pw')
        self.development = Development.objects.create(name='Estate')
        # base 1000, parking 100, quoted 1200
        self.building, self.flats = make_project('Tower', floors=1, units=2, development=self.development)
        self.customer = Customer.objects.create(name='Rahim', phone='01711000001')

    def data(self, flat=None, **extra):
        return {
            'flat': (flat or self.flats[0]).pk, 'customer': self.customer.pk, 'sale_date': '2026-02-01',
            'flat_sale_value': '1200', 'reg_value': '0', **extra,
        }

    def book(self, **extra):
        form = FlatSaleForm(data=self.data(**extra))
        self.assertTrue(form.is_valid(), form.errors)
        return form.save()


class SplitTests(ParkingSaleValueTestCase):
    def test_the_sale_value_is_the_flat_value_plus_the_parking_value(self):
        sale = self.book(with_parking='on', flat_sale_value='1300', parking_sale_value='250', reg_value='50')
        self.assertEqual((sale.flat_sale_value, sale.parking_sale_value, sale.sale_value), (1300, 250, 1550))
        self.assertEqual(sale.net_value, 1600)

    def test_honorarium_is_worked_out_for_each_part_and_adds_up(self):
        sale = self.book(with_parking='on', flat_sale_value='1300', parking_sale_value='250')
        self.assertEqual((sale.flat_honorarium, sale.parking_honorarium), (300, 150))   # 1300-1000, 250-100
        self.assertEqual(sale.honorarium, sale.flat_honorarium + sale.parking_honorarium)
        self.assertEqual(sale.total_base_price, 1100)

    def test_without_parking_the_whole_sale_value_is_the_flat(self):
        sale = self.book(flat_sale_value='1250', parking_sale_value='999')   # a typed parking value is ignored
        self.assertEqual((sale.flat_sale_value, sale.parking_sale_value, sale.sale_value), (1250, 0, 1250))
        self.assertEqual(sale.parking_honorarium, 0)

    def test_parking_taken_without_a_value_is_sold_at_its_price(self):
        sale = self.book(with_parking='on')
        self.assertEqual((sale.parking_sale_value, sale.flat_sale_value, sale.sale_value), (100, 1200, 1300))

    def test_each_part_has_its_own_minimum(self):
        flat = FlatSaleForm(data=self.data(with_parking='on', flat_sale_value='999', parking_sale_value='500'))
        self.assertFalse(flat.is_valid())
        self.assertEqual(list(flat.errors), ['flat_sale_value'])
        parking = FlatSaleForm(data=self.data(with_parking='on', flat_sale_value='5000', parking_sale_value='99'))
        self.assertFalse(parking.is_valid())
        self.assertEqual(list(parking.errors), ['parking_sale_value'])

    def test_a_big_flat_value_cannot_make_up_for_a_cheap_parking_lot(self):
        form = FlatSaleForm(data=self.data(with_parking='on', flat_sale_value='5000', parking_sale_value='50'))
        self.assertFalse(form.is_valid())

    def test_editing_shows_the_two_values_and_keeps_them(self):
        sale = self.book(with_parking='on', flat_sale_value='1300', parking_sale_value='250')
        form = FlatSaleForm(instance=sale)
        self.assertEqual((form.initial['flat_sale_value'], form.initial['parking_sale_value']), (1300, 250))
        data = self.data(with_parking='on', flat_sale_value='1400', parking_sale_value='250')
        again = FlatSaleForm(data=data, instance=sale)
        self.assertTrue(again.is_valid(), again.errors)
        self.assertEqual(again.save().sale_value, 1650)

    def test_unticking_parking_when_editing_removes_its_value(self):
        sale = self.book(with_parking='on', flat_sale_value='1300', parking_sale_value='250')
        form = FlatSaleForm(data=self.data(flat_sale_value='1300'), instance=sale)
        self.assertTrue(form.is_valid(), form.errors)
        saved = form.save()
        self.assertEqual((saved.parking_sale_value, saved.parking_price, saved.sale_value), (0, 0, 1300))

    def test_a_sale_entered_as_one_total_takes_the_parking_lot_at_its_price(self):
        sale = FlatSale.objects.create(
            flat=self.flats[1], customer=self.customer, sale_date='2026-02-01', with_parking=True, sale_value=1500,
        )
        self.assertEqual((sale.parking_sale_value, sale.flat_sale_value), (100, 1400))

    def test_the_total_in_every_report_and_list_is_unchanged(self):
        sale = self.book(with_parking='on', flat_sale_value='1300', parking_sale_value='250')
        self.assertEqual(FlatSale.objects.get(pk=sale.pk).sale_value, 1550)


class CalculationOnScreenTests(ParkingSaleValueTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.user)
        unlock_client(self.client)
        enter_project(self.client, self.development)
        self.sale = self.book(with_parking='on', flat_sale_value='1300', parking_sale_value='250', reg_value='50')

    def test_the_sale_page_shows_every_step_of_the_calculation(self):
        page = self.client.get(reverse('sales:detail', args=[self.sale.pk])).content.decode()
        for text in ('Sale value calculation', 'Flat', 'Parking', 'Total', 'Base price', 'Honorarium',
                     '1,300.00', '250.00', '1,550.00', '300.00', '150.00', '450.00', '1,100.00', '1,600.00'):
            self.assertIn(text, page, text)

    def test_the_booking_form_has_the_two_value_fields_and_the_calculation_table(self):
        page = self.client.get(reverse('sales:create')).content.decode()
        self.assertIn('id_flat_sale_value', page)
        self.assertIn('id_parking_sale_value', page)
        self.assertIn('id="pv-flat-hon"', page)
        self.assertIn('id="pv-parking-hon"', page)
        self.assertIn('id="pv-net"', page)

    def test_the_edit_form_comes_filled_in(self):
        page = self.client.get(reverse('sales:update', args=[self.sale.pk])).content.decode()
        self.assertIn('value="1300.00"', page)
        self.assertIn('value="250.00"', page)

    def test_the_invoice_lists_flat_and_parking_separately(self):
        page = self.client.get(reverse('sales:invoice', args=[self.sale.pk])).content.decode()
        self.assertIn('1,300.00', page)
        self.assertIn('250.00', page)
        self.assertIn('Parking lot', page)

    def test_booking_through_the_form_page_saves_both_values(self):
        data = self.data(self.flats[1], with_parking='on', flat_sale_value='1210', parking_sale_value='130')
        self.assertEqual(self.client.post(reverse('sales:create'), data).status_code, 302)
        sale = FlatSale.objects.get(flat=self.flats[1])
        self.assertEqual((sale.flat_sale_value, sale.parking_sale_value, sale.sale_value), (1210, 130, 1340))

    def test_locked_screens_show_no_base_price_or_honorarium_on_the_form(self):
        locked = self.client.__class__()
        locked.force_login(self.user)
        enter_project(locked, self.development)
        page = re.sub(r'<nav.*?</nav>', '', locked.get(reverse('sales:create')).content.decode(), flags=re.S)  # the menu names Honorarium
        self.assertNotIn('"base":', page)  
        self.assertNotIn('Base price', page)
        self.assertNotIn('Honorarium', page)
        self.assertIn('id="pv-sale"', page)
