from django.test import TestCase

from costing.models import CostCategory

from .forms import SupplierForm
from .models import Supplier


class SupplierTests(TestCase):
    def data(self, **extra):
        return {'name': 'Rahman Traders Ltd', **extra}

    def test_company_profile_fields_are_saved(self):
        civil = CostCategory.objects.create(name='Civil')
        form = SupplierForm(data=self.data(
            owner_name='Mr. Rahman', phone='01711222333', email='rahman@example.com', tin='123456789012',
            address='Dhaka', bank_account='Demo Bank, 1234567', cost_category=civil.pk, notes='Reliable',
        ))
        self.assertTrue(form.is_valid(), form.errors)
        supplier = form.save()
        self.assertEqual((supplier.name, supplier.owner_name, supplier.email), ('Rahman Traders Ltd', 'Mr. Rahman', 'rahman@example.com'))
        self.assertEqual((supplier.bank_account, supplier.cost_category), ('Demo Bank, 1234567', civil))
        self.assertEqual(supplier.tin, '123456789012')

    def test_only_the_company_name_is_required(self):
        self.assertTrue(SupplierForm(data=self.data()).is_valid())
        self.assertFalse(SupplierForm(data={'owner_name': 'X'}).is_valid())

    def test_phone_gets_the_88_prefix(self):
        supplier = SupplierForm(data=self.data(phone='01711222333')).save()
        self.assertEqual(supplier.phone, '+8801711222333')

    def test_type_uses_the_cost_categories(self):
        field = SupplierForm().fields['cost_category']
        self.assertEqual(field.label, 'Type')
        CostCategory.objects.create(name='Electrical')
        self.assertIn('Electrical', [str(c) for c in field.queryset])

    def test_supplier_code_format(self):
        supplier = Supplier.objects.create(name='A')
        self.assertRegex(supplier.supplier_code, r'^[A-Z]+-S-\d{3}$')

    def test_total_cost_adds_the_supplier_costs(self):
        from core.testing import make_project
        from costing.models import ProjectCost
        project, _ = make_project()
        supplier = Supplier.objects.create(name='A')
        civil = CostCategory.objects.create(name='Civil')
        for amount in (100, 250):
            ProjectCost.objects.create(project=project, cost_category=civil, supplier=supplier, date='2026-01-01', amount=amount)
        self.assertEqual(supplier.total_cost, 350)
