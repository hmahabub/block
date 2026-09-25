from django.test import TestCase

from .forms import CustomerForm
from .models import Customer


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

    def test_phone_must_still_be_unique(self):
        Customer.objects.create(name='A', phone='+8801711000001')
        self.assertIn('phone', CustomerForm(data=self.data()).errors)
