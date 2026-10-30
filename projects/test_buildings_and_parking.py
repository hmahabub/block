import time
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase

from core.testing import make_project, make_request
from customers.models import Customer
from sales.forms import FlatSaleForm
from sales.models import FlatSale

from .forms import FlatForm, ProjectForm
from .models import Development, Project
from .views import (
    DevelopmentDeleteView,
    DevelopmentDetailView,
    DevelopmentListView,
    FlatDetailView,
    ProjectListView,
)

D = Decimal


class ProjectAndBuildingTests(TestCase):
    """A Project (land) holds one or more Buildings; each building holds the flats."""

    def setUp(self):
        self.user = User.objects.create_superuser('boss', 'b@example.com', 'pw')
        self.estate = Development.objects.create(name='Dar Al Jannah Estate', location='Dhaka')

    def building(self, name, **extra):
        return Project.objects.create(project_name=name, development=self.estate, **extra)

    def test_a_project_gets_its_own_code(self):
        self.assertRegex(self.estate.code, r'^[A-Z]+-PRJ-\d{3}$')
        self.assertEqual(Development.objects.create(name='Second').code[-3:], '002')

    def test_one_project_holds_several_buildings(self):
        self.building('Tower 1')
        self.building('Tower 2')
        self.assertEqual(self.estate.building_count, 2)
        self.assertEqual({b.development for b in Project.objects.all()}, {self.estate})

    def test_the_project_adds_up_its_buildings(self):
        _, flats_a = make_project('A', floors=1, units=2)
        _, flats_b = make_project('B', floors=1, units=3)
        Project.objects.filter(project_name__in=['A', 'B']).update(development=self.estate)
        self.assertEqual((self.estate.flat_count, self.estate.sold_flat_count), (5, 0))
        customer = Customer.objects.create(name='C', phone='01711111111')
        FlatSale.objects.create(flat=flats_b[0], customer=customer, sale_date='2026-01-01', sale_value=1200)
        self.assertEqual(self.estate.sold_flat_count, 1)
        self.assertEqual(self.estate.total_sales_value, 1200)

    def test_a_new_building_must_name_its_project(self):
        data = {'project_name': 'T', 'status': 'PLANNING', 'floor_no': 1, 'land_area': 0, 'budget_amount': 0,
                'flat_type': '2BED', 'flat_area': 1000, 'base_price': 1000, 'quoted_price': 1000, 'parking_price': 0}
        form = ProjectForm(data=data)
        self.assertFalse(form.is_valid())
        self.assertIn('development', form.errors)
        self.assertTrue(ProjectForm(data={**data, 'development': self.estate.pk}).is_valid())

    def test_buildings_older_than_projects_still_work_without_one(self):
        old = Project.objects.create(project_name='Old')
        self.assertIsNone(old.development)
        self.assertEqual(old.flat_count, 0)

    def test_a_project_with_buildings_cannot_be_deleted(self):
        self.building('Tower 1')
        response = DevelopmentDeleteView.as_view()(make_request(self.user, '/', 'post'), pk=self.estate.pk)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Development.objects.filter(pk=self.estate.pk).exists())

    def test_an_empty_project_can_be_deleted(self):
        empty = Development.objects.create(name='Empty')
        DevelopmentDeleteView.as_view()(make_request(self.user, '/', 'post'), pk=empty.pk)
        self.assertFalse(Development.objects.filter(pk=empty.pk).exists())

    def test_the_pages_render(self):
        self.building('Tower 1')
        cases = ((DevelopmentListView, {}, 'Dar Al Jannah Estate'), (DevelopmentDetailView, {'pk': self.estate.pk}, 'Tower 1'),
                 (ProjectListView, {}, 'Tower 1'))
        for view, kwargs, expected in cases:
            response = view.as_view()(make_request(self.user, '/'), **kwargs)
            response.render()
            self.assertEqual(response.status_code, 200)
            self.assertIn(expected, response.content.decode())

    def test_the_building_list_can_be_filtered_by_project(self):
        other = Development.objects.create(name='Other')
        self.building('Tower 1')
        Project.objects.create(project_name='Elsewhere', development=other)
        view = ProjectListView()
        view.setup(make_request(self.user, '/', data={'development': self.estate.pk}))
        self.assertEqual([b.project_name for b in view.get_queryset()], ['Tower 1'])

    def test_screens_call_a_building_a_building(self):
        response = ProjectListView.as_view()(make_request(self.user, '/'))
        response.render()
        html = response.content.decode()
        self.assertIn('Buildings', html)
        self.assertIn('Add New Building', html)


class ParkingPricePerFlatTests(TestCase):
    """The building has a default parking price (100); each flat can have its own."""

    def setUp(self):
        self.project, self.flats = make_project(floors=1, units=3)   # base 1000, quoted 1200, parking 100
        self.customer = Customer.objects.create(name='C', phone='01711111111')

    def sell(self, flat, value=1500, parking=True):
        return FlatSale.objects.create(flat=flat, customer=self.customer, sale_date='2026-01-01', sale_value=value, with_parking=parking)

    def test_a_flat_uses_the_building_default_until_it_has_its_own(self):
        flat = self.flats[0]
        self.assertIsNone(flat.parking_price)
        self.assertEqual(flat.effective_parking_price, 100)
        flat.parking_price = D('250')
        flat.save()
        self.assertEqual(flat.effective_parking_price, 250)

    def test_a_free_parking_lot_is_a_real_price_of_zero(self):
        flat = self.flats[0]
        flat.parking_price = D('0')
        flat.save()
        self.assertEqual(flat.effective_parking_price, 0)

    def test_two_flats_can_have_different_parking_prices(self):
        a, b = self.flats[0], self.flats[1]
        a.parking_price = D('300')
        a.save()
        sale_a, sale_b = self.sell(a), self.sell(b)
        self.assertEqual((sale_a.parking_price, sale_a.total_base_price), (300, 1300))
        self.assertEqual((sale_b.parking_price, sale_b.total_base_price), (100, 1100))

    def test_the_honorarium_follows_the_flats_own_parking_price(self):
        flat = self.flats[0]
        flat.parking_price = D('400')
        flat.save()
        self.assertEqual(self.sell(flat, value=1800).honorarium, 400)   # 1800 - (1000 + 400)

    def test_a_sale_keeps_its_parking_price_when_the_flat_price_changes_later(self):
        flat = self.flats[0]
        sale = self.sell(flat)
        flat.parking_price = D('999')
        flat.save()
        sale.refresh_from_db()
        sale.save()
        self.assertEqual(sale.parking_price, 100)

    def test_the_sale_form_checks_against_the_flats_parking_price(self):
        flat = self.flats[0]
        flat.parking_price = D('500')
        flat.save()
        data = {'flat': flat.pk, 'customer': self.customer.pk, 'sale_date': '2026-02-01', 'with_parking': 'on', 'reg_value': '0'}
        self.assertFalse(FlatSaleForm(data={**data, 'sale_value': '1400'}).is_valid())   # needs at least 1000 + 500
        self.assertTrue(FlatSaleForm(data={**data, 'sale_value': '1500'}).is_valid())
        other = {**data, 'flat': self.flats[1].pk}
        self.assertTrue(FlatSaleForm(data={**other, 'sale_value': '1100'}).is_valid())   # the building default, 100

    def test_the_live_preview_data_has_each_flats_own_price(self):
        flat = self.flats[0]
        flat.parking_price = D('500')
        flat.save()
        prices = FlatSaleForm().price_map()
        self.assertEqual((prices[flat.pk]['parking'], prices[self.flats[1].pk]['parking']), ('500.00', '100.00'))

    def test_the_flat_form_takes_an_optional_parking_price(self):
        data = {'unit': 'C', 'floor_no': 5, 'facing': '', 'parking_lot': '', 'notes': ''}
        blank = FlatForm(data=data, project=self.project)
        self.assertTrue(blank.is_valid(), blank.errors)
        self.assertIsNone(blank.cleaned_data['parking_price'])
        priced = FlatForm(data={**data, 'parking_price': '250000'}, project=self.project)
        self.assertTrue(priced.is_valid(), priced.errors)
        self.assertEqual(priced.cleaned_data['parking_price'], 250000)
        self.assertFalse(FlatForm(data={**data, 'parking_price': '-5'}, project=self.project).is_valid())

    def test_the_flat_page_shows_the_price(self):
        flat = self.flats[0]
        flat.parking_price = D('777')
        flat.save()
        user = User.objects.create_superuser('boss', 'b@example.com', 'pw')
        request = make_request(user, '/', session={'reauth_until': time.time() + 600, 'reauth_token': 't'},
                               cookies={'daj_unlocked': 't'})
        response = FlatDetailView.as_view()(request, pk=flat.pk)
        response.render()
        html = response.content.decode()
        self.assertIn('777.00', html)
        self.assertIn('set for this flat', html)
