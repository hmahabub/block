import re

from django.db import IntegrityError, transaction
from django.test import TestCase

from core.numbering import generate_plain_code
from suppliers.forms import SupplierForm
from suppliers.models import Supplier

from .forms import CustomerForm
from .models import Customer


def make(name, phone, **extra):
    return Customer.objects.create(name=name, phone=phone, **extra)


class CustomerIdTests(TestCase):
    def test_ids_are_c_and_four_digits_in_order(self):
        codes = [make(f'N{n}', f'0171100000{n}').customer_code for n in range(3)]
        self.assertEqual(codes, ['C0001', 'C0002', 'C0003'])
        self.assertTrue(all(re.fullmatch(r'C\d{4}', code) for code in codes))

    def test_an_id_never_changes_when_the_customer_is_edited(self):
        customer = make('A', '01711000001')
        code = customer.customer_code
        customer.name = 'A renamed'
        customer.phone = '01711000099'
        customer.save()
        customer.refresh_from_db()
        self.assertEqual(customer.customer_code, code)

    def test_an_id_is_never_reused_after_a_customer_is_deleted(self):
        first = make('A', '01711000001')
        make('B', '01711000002')
        first.delete()
        self.assertEqual(make('C', '01711000003').customer_code, 'C0003')

    def test_the_id_cannot_be_typed_into_the_form(self):
        self.assertNotIn('customer_code', CustomerForm().fields)
        form = CustomerForm(data={'name': 'A', 'phone': '01711000001', 'customer_code': 'C9999'})
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.save().customer_code, 'C0001')

    def test_ids_are_unique_in_the_database(self):
        customer = make('A', '01711000001')
        with self.assertRaises(IntegrityError), transaction.atomic():
            Customer.objects.filter(pk=make('B', '01711000002').pk).update(customer_code=customer.customer_code)

    def test_the_plain_code_helper(self):
        self.assertEqual(generate_plain_code('widget', 'W'), 'W0001')
        self.assertEqual(generate_plain_code('widget', 'W', width=2), 'W02')

    def test_the_list_search_finds_an_id(self):
        from customers.views import CustomerListView
        from core.testing import make_request
        from django.contrib.auth.models import User
        make('Rahim', '01711000001')
        target = make('Karim', '01711000002')
        view = CustomerListView()
        view.setup(make_request(User.objects.create_superuser('b', 'b@example.com', 'pw'), '/', data={'q': target.customer_code}))
        self.assertEqual([c.name for c in view.get_queryset()], ['Karim'])

    def test_the_id_shows_on_the_list_and_detail_pages(self):
        from customers.views import CustomerDetailView, CustomerListView
        from core.testing import make_request
        from django.contrib.auth.models import User
        user = User.objects.create_superuser('b', 'b@example.com', 'pw')
        customer = make('Rahim', '01711000001')
        for view, kwargs in ((CustomerListView, {}), (CustomerDetailView, {'pk': customer.pk})):
            response = view.as_view()(make_request(user, '/'), **kwargs)
            response.render()
            self.assertIn('C0001', response.content.decode())


class NidAndTinUniqueTests(TestCase):
    def data(self, **extra):
        return {'name': 'New', 'phone': '01711000077', 'nationality': 'Bangladeshi', **extra}

    def test_the_same_nid_cannot_be_used_twice(self):
        make('A', '01711000001', identification_no='1990123456789')
        form = CustomerForm(data=self.data(identification_no='1990123456789'))
        self.assertFalse(form.is_valid())
        self.assertIn('already belongs to customer C0001', str(form.errors['identification_no']))

    def test_the_same_tin_cannot_be_used_twice(self):
        make('A', '01711000001', tin='123456789012')
        form = CustomerForm(data=self.data(tin='123456789012'))
        self.assertFalse(form.is_valid())
        self.assertIn('tin', form.errors)

    def test_the_check_ignores_case_and_stray_spaces(self):
        make('A', '01711000001', identification_no='AB123456')
        self.assertFalse(CustomerForm(data=self.data(identification_no='  ab123456 ')).is_valid())

    def test_blank_nid_and_tin_are_fine_for_many_customers(self):
        for n in range(3):
            self.assertTrue(CustomerForm(data=self.data(phone=f'0171100010{n}')).save())
        self.assertEqual(Customer.objects.filter(identification_no='', tin='').count(), 3)

    def test_a_customer_keeps_their_own_number_when_edited(self):
        customer = make('A', '01711000001', identification_no='111', tin='222')
        form = CustomerForm(data=self.data(phone='01711000001', identification_no='111', tin='222', name='A2'), instance=customer)
        self.assertTrue(form.is_valid(), form.errors)

    def test_nid_and_tin_are_separate_numbers(self):
        make('A', '01711000001', identification_no='555')
        self.assertTrue(CustomerForm(data=self.data(tin='555')).is_valid())   # same digits in the other field is fine

    def test_the_database_refuses_duplicates_even_if_a_form_is_bypassed(self):
        make('A', '01711000001', identification_no='777', tin='888')
        with self.assertRaises(IntegrityError), transaction.atomic():
            make('B', '01711000002', identification_no='777')
        with self.assertRaises(IntegrityError), transaction.atomic():
            make('C', '01711000003', tin='888')

    def test_stray_spaces_are_stripped_on_save(self):
        customer = make('A', '01711000001', identification_no=' 999 ', tin=' 321 ')
        customer.refresh_from_db()
        self.assertEqual((customer.identification_no, customer.tin), ('999', '321'))

    def test_the_error_message_names_the_other_customer(self):
        make('Rahim Uddin', '01711000001', tin='TIN-1')
        form = CustomerForm(data=self.data(tin='TIN-1'))
        form.is_valid()
        self.assertIn('Rahim Uddin', str(form.errors['tin']))


class SupplierTinUniqueTests(TestCase):
    def test_two_suppliers_cannot_share_a_tin(self):
        Supplier.objects.create(name='A', tin='123456789012')
        form = SupplierForm(data={'name': 'B', 'tin': '123456789012'})
        self.assertFalse(form.is_valid())
        self.assertIn('already belongs to supplier', str(form.errors['tin']))

    def test_blank_tins_are_fine(self):
        Supplier.objects.create(name='A')
        self.assertTrue(SupplierForm(data={'name': 'B'}).is_valid())
        Supplier.objects.create(name='B')

    def test_the_database_enforces_it_too(self):
        Supplier.objects.create(name='A', tin='42')
        with self.assertRaises(IntegrityError), transaction.atomic():
            Supplier.objects.create(name='B', tin='42')

    def test_a_supplier_can_be_edited_without_clashing_with_itself(self):
        supplier = Supplier.objects.create(name='A', tin='42')
        form = SupplierForm(data={'name': 'A2', 'tin': '42'}, instance=supplier)
        self.assertTrue(form.is_valid(), form.errors)
