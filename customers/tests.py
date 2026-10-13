from django.test import TestCase

from core.phone import normalize_phone

from .forms import CustomerForm
from .models import Customer


class PhoneNormalizationTests(TestCase):
    def test_local_numbers_get_the_88_prefix(self):
        self.assertEqual(normalize_phone('01711000001'), '+8801711000001')
        self.assertEqual(normalize_phone('01711-000 001'), '+8801711000001')

    def test_numbers_already_in_international_form_are_kept(self):
        self.assertEqual(normalize_phone('+8801711000001'), '+8801711000001')
        self.assertEqual(normalize_phone('+14155550123'), '+14155550123')

    def test_88_without_a_plus_and_00_prefix_are_fixed_up(self):
        self.assertEqual(normalize_phone('8801711000001'), '+8801711000001')
        self.assertEqual(normalize_phone('008801711000001'), '+8801711000001')

    def test_blank_stays_blank(self):
        self.assertEqual(normalize_phone(''), '')

    def test_the_model_normalises_on_save(self):
        customer = Customer.objects.create(name='A', phone='01711000001', whatsapp_no='01711000002')
        self.assertEqual((customer.phone, customer.whatsapp_no), ('+8801711000001', '+8801711000002'))


class CustomerFormTests(TestCase):
    def data(self, **extra):
        return {'name': 'Rahim', 'phone': '+8801711000001', 'nationality': 'Bangladeshi', **extra}

    def test_only_name_and_phone_are_required(self):
        self.assertTrue(CustomerForm(data=self.data()).is_valid())

    def test_saves_family_and_nominee_details(self):
        form = CustomerForm(data=self.data(
            father_name='Karim', mother_name='Amina', spouse_name='Salma',
            date_of_birth='1985-04-12', occupation='Engineer',
            nominee_name='Salma', nominee_relation='Wife',
        ))
        self.assertTrue(form.is_valid(), form.errors)
        customer = form.save()
        self.assertEqual((customer.father_name, customer.mother_name, customer.spouse_name), ('Karim', 'Amina', 'Salma'))
        self.assertEqual(str(customer.date_of_birth), '1985-04-12')
        self.assertEqual((customer.nominee_name, customer.nominee_relation), ('Salma', 'Wife'))

    def test_saves_the_new_profile_fields(self):
        form = CustomerForm(data=self.data(
            title='MS', whatsapp_no='01711000009', tin='123456789012',
            emergency_contact_name='Karim', emergency_contact_phone='01711000008',
        ))
        self.assertTrue(form.is_valid(), form.errors)
        customer = form.save()
        self.assertEqual((customer.title, customer.display_name), ('MS', 'Ms. Rahim'))
        self.assertEqual((customer.whatsapp_no, customer.emergency_contact_phone), ('+8801711000009', '+8801711000008'))
        self.assertEqual((customer.tin, customer.emergency_contact_name), ('123456789012', 'Karim'))

    def test_title_is_optional_and_limited_to_mr_or_ms(self):
        self.assertTrue(CustomerForm(data=self.data(title='')).is_valid())
        self.assertFalse(CustomerForm(data=self.data(title='DR')).is_valid())
        self.assertEqual(Customer(name='Karim').display_name, 'Karim')

    def test_sms_is_on_for_a_new_customer_and_can_be_switched_off(self):
        self.assertTrue(CustomerForm().fields['sms_enabled'].initial)  # pre-ticked on the new-customer form
        ticked = CustomerForm(data={**self.data(), 'sms_enabled': 'on'})
        self.assertTrue(ticked.save().sms_enabled)
        unticked = CustomerForm(data=self.data(phone='01711000077'))  # an unticked box is simply not posted
        self.assertTrue(unticked.is_valid(), unticked.errors)
        self.assertFalse(unticked.save().sms_enabled)

    def test_phone_is_normalised_by_the_form(self):
        customer = CustomerForm(data=self.data(phone='01711000001')).save()
        self.assertEqual(customer.phone, '+8801711000001')

    def test_same_as_present_copies_the_address(self):
        form = CustomerForm(data=self.data(present_address='House 1, Dhaka', same_as_present='on'))
        self.assertTrue(form.is_valid(), form.errors)
        customer = form.save()
        self.assertEqual(customer.permanent_address, 'House 1, Dhaka')

    def test_separate_permanent_address_is_kept(self):
        form = CustomerForm(data=self.data(present_address='Dhaka', permanent_address='Comilla'))
        customer = form.save()
        self.assertEqual((customer.present_address, customer.permanent_address), ('Dhaka', 'Comilla'))

    def test_checkbox_preticked_only_when_addresses_match(self):
        same = Customer.objects.create(name='A', phone='+8801711000002', present_address='X', permanent_address='X')
        different = Customer.objects.create(name='B', phone='+8801711000003', present_address='X', permanent_address='Y')
        blank = Customer.objects.create(name='C', phone='+8801711000004')
        self.assertTrue(CustomerForm(instance=same).fields['same_as_present'].initial)
        self.assertFalse(CustomerForm(instance=different).fields['same_as_present'].initial)
        self.assertFalse(CustomerForm(instance=blank).fields['same_as_present'].initial)

    def test_phone_must_be_unique_even_when_typed_differently(self):
        Customer.objects.create(name='A', phone='+8801711000001')
        for typed in ('+8801711000001', '01711000001', '8801711000001'):
            self.assertIn('phone', CustomerForm(data=self.data(phone=typed)).errors, typed)

    def test_editing_a_customer_keeps_their_own_phone(self):
        customer = Customer.objects.create(name='A', phone='+8801711000001')
        form = CustomerForm(data=self.data(phone='01711000001', name='A2'), instance=customer)
        self.assertTrue(form.is_valid(), form.errors)

    def test_receivable_ignores_cancelled_bookings(self):
        from core.testing import make_project
        from sales.models import FlatSale
        _, flats = make_project()
        customer = Customer.objects.create(name='A', phone='01711000001')
        FlatSale.objects.create(flat=flats[0], customer=customer, sale_date='2026-01-01', sale_value=1200)
        dropped = FlatSale.objects.create(flat=flats[1], customer=customer, sale_date='2026-01-01', sale_value=1200)
        dropped.cancel(100)
        dropped.save()
        self.assertEqual(customer.total_receivable, 1200)
