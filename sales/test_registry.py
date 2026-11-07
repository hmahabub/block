"""Flat status: Available (green), Booked (yellow), Registered once the registry is completed (red)."""
import datetime

from django.contrib.auth.models import Permission, User
from django.template import Context, Template
from django.test import TestCase
from django.urls import reverse

from core.testing import enter_project, make_project, unlock_client
from customers.models import Customer
from projects.models import Development, Flat

from .models import FlatSale


class RegistryTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser('boss', 'b@example.com', 'pw')
        self.development = Development.objects.create(name='Estate')
        self.building, self.flats = make_project('Tower', floors=1, units=3, development=self.development)
        self.customer = Customer.objects.create(name='Rahim', phone='01711000001')
        self.flat = self.flats[0]

    def book(self, flat=None):
        return FlatSale.objects.create(flat=flat or self.flat, customer=self.customer, sale_date='2026-01-01', sale_value=1500)

    def status(self, flat=None):
        return Flat.objects.get(pk=(flat or self.flat).pk).status


class StatusFlowTests(RegistryTestCase):
    def test_a_flat_starts_available(self):
        self.assertEqual(self.status(), Flat.Status.AVAILABLE)

    def test_booking_makes_the_flat_and_the_sale_booked(self):
        sale = self.book()
        self.assertEqual((sale.status, self.status()), (FlatSale.Status.BOOKED, Flat.Status.BOOKED))
        self.assertIsNone(sale.registered_on)

    def test_completing_the_registry_makes_both_registered(self):
        sale = self.book()
        sale.register(datetime.date(2026, 3, 1))
        sale.save()
        self.assertEqual((sale.status, str(sale.registered_on), self.status()), (FlatSale.Status.REGISTERED, '2026-03-01', Flat.Status.REGISTERED))

    def test_undoing_the_registry_goes_back_to_booked(self):
        sale = self.book()
        sale.register()
        sale.save()
        sale.undo_registry()
        sale.save()
        self.assertEqual((sale.status, self.status()), (FlatSale.Status.BOOKED, Flat.Status.BOOKED))

    def test_editing_a_registered_sale_keeps_it_registered(self):
        sale = self.book()
        sale.register()
        sale.save()
        sale.reg_value = 50
        sale.save()
        self.assertEqual((sale.status, self.status()), (FlatSale.Status.REGISTERED, Flat.Status.REGISTERED))

    def test_a_cancelled_sale_frees_the_flat(self):
        sale = self.book()
        sale.cancel(100)
        sale.save()
        self.assertEqual((sale.status, self.status()), (FlatSale.Status.CANCELLED, Flat.Status.AVAILABLE))

    def test_counts_of_flats_by_status(self):
        booked, registered = self.book(self.flats[0]), self.book(self.flats[1])
        registered.register()
        registered.save()
        building = self.building
        self.assertEqual((building.available_flat_count, building.booked_flat_count, building.registered_flat_count), (1, 1, 1))
        self.assertEqual(building.sold_flat_count, 2)
        self.assertEqual(booked.flat.status, Flat.Status.BOOKED)


class ColourTests(TestCase):
    def render(self, status):
        return Template('{% load core_tags %}{{ s|status_badge }}').render(Context({'s': status}))

    def test_available_is_green_booked_yellow_registered_red(self):
        self.assertEqual(self.render('AVAILABLE'), 'bg-success')
        self.assertEqual(self.render('BOOKED'), 'bg-warning text-dark')
        self.assertEqual(self.render('REGISTERED'), 'bg-danger')

    def test_a_cancelled_sale_is_grey_so_it_is_not_mistaken_for_registered(self):
        self.assertEqual(self.render('CANCELLED'), 'bg-secondary')


class RegistryScreenTests(RegistryTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.user)
        unlock_client(self.client)
        enter_project(self.client, self.development)
        self.sale = self.book()

    def registry(self, **data):
        return self.client.post(reverse('sales:registry', args=[self.sale.pk]), data)

    def test_the_sale_page_offers_to_mark_it_registered(self):
        page = self.client.get(reverse('sales:detail', args=[self.sale.pk])).content.decode()
        self.assertIn('Mark registered', page)
        self.assertIn('registry not completed yet', page)

    def test_marking_it_registered_through_the_page(self):
        self.assertEqual(self.registry(registered_on='2026-03-05').status_code, 302)
        self.sale.refresh_from_db()
        self.assertEqual((self.sale.status, str(self.sale.registered_on), self.status()), ('REGISTERED', '2026-03-05', 'REGISTERED'))
        page = self.client.get(reverse('sales:detail', args=[self.sale.pk])).content.decode()
        self.assertIn('completed on 5 Mar 2026', page)
        self.assertIn('Undo registry', page)

    def test_a_missing_or_bad_date_means_today(self):
        self.registry(registered_on='nonsense')
        self.sale.refresh_from_db()
        self.assertEqual(self.sale.registered_on, datetime.date.today())

    def test_undoing_it_through_the_page(self):
        self.registry(registered_on='2026-03-05')
        self.registry(action='undo')
        self.sale.refresh_from_db()
        self.assertEqual((self.sale.status, self.sale.registered_on), ('BOOKED', None))

    def test_a_registered_sale_cannot_be_cancelled_until_the_registry_is_undone(self):
        self.registry(registered_on='2026-03-05')
        page = self.client.get(reverse('sales:detail', args=[self.sale.pk])).content.decode()
        self.assertNotIn('Cancel sale', page)
        response = self.client.get(reverse('sales:cancel', args=[self.sale.pk]))
        self.assertRedirects(response, reverse('sales:detail', args=[self.sale.pk]))
        self.client.post(reverse('sales:cancel', args=[self.sale.pk]), {'refund_percent': '100', 'cancelled_on': '2026-04-01'})
        self.sale.refresh_from_db()
        self.assertEqual(self.sale.status, 'REGISTERED')

    def test_a_cancelled_sale_has_no_registry(self):
        self.sale.cancel(100)
        self.sale.save()
        self.registry(registered_on='2026-03-05')
        self.sale.refresh_from_db()
        self.assertEqual((self.sale.status, self.sale.registered_on), ('CANCELLED', None))

    def test_the_registry_needs_permission_and_a_post(self):
        self.assertEqual(self.client.get(reverse('sales:registry', args=[self.sale.pk])).status_code, 405)
        clerk = User.objects.create_user('clerk', password='pw')
        clerk.user_permissions.add(Permission.objects.get(codename='view_flatsale'))
        self.client.force_login(clerk)
        enter_project(self.client, self.development)
        self.assertEqual(self.registry(registered_on='2026-03-05').status_code, 403)
        self.sale.refresh_from_db()
        self.assertEqual(self.sale.status, 'BOOKED')

    def test_another_projects_sale_cannot_be_registered(self):
        other = Development.objects.create(name='Other')
        enter_project(self.client, other)
        self.assertEqual(self.registry(registered_on='2026-03-05').status_code, 404)

    def test_the_booking_map_colours_each_flat(self):
        registered = self.book(self.flats[1])
        registered.register()
        registered.save()
        page = self.client.get(reverse('projects:detail', args=[self.building.pk])).content.decode()
        for css in ('seat seat-available', 'seat seat-booked', 'seat seat-registered'):
            self.assertIn(css, page, css)
        for label in ('Available', 'Booked', 'Registered'):
            self.assertIn(label, page)

    def test_the_flat_list_badges_use_the_colours(self):
        registered = self.book(self.flats[1])
        registered.register()
        registered.save()
        page = self.client.get(reverse('projects:flat-list'), {'project': self.building.pk}).content.decode()
        for css in ('badge bg-success', 'badge bg-warning text-dark', 'badge bg-danger'):
            self.assertIn(css, page, css)

    def test_the_flat_list_can_be_filtered_by_the_new_statuses(self):
        registered = self.book(self.flats[1])
        registered.register()
        registered.save()
        response = self.client.get(reverse('projects:flat-list'), {'project': self.building.pk, 'status': 'REGISTERED'})
        self.assertEqual([f.pk for f in response.context['object_list']], [self.flats[1].pk])

    def test_the_home_page_counts_each_status(self):
        registered = self.book(self.flats[1])
        registered.register()
        registered.save()
        context = self.client.get(reverse('home')).context
        self.assertEqual((context['available_count'], context['booked_count'], context['registered_count']), (1, 1, 1))
