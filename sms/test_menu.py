"""SMS has a menu of its own, apart from Sales."""
from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse

from core.testing import enter_project, make_project, unlock_client
from projects.models import Development


class SmsMenuTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser('boss', 'b@example.com', 'pw')
        development = Development.objects.create(name='Estate')
        make_project('Tower', floors=1, units=1, development=development)
        self.client.force_login(self.user)
        unlock_client(self.client)
        enter_project(self.client, development)

    def menus(self):
        page = self.client.get(reverse('home')).content.decode()
        sales = page[page.index('fa-dollar-sign'):page.index('fa-sms')]
        sms = page[page.index('fa-sms'):page.index('fa-user-tie')]
        return sales, sms

    def test_the_sms_pages_are_in_their_own_menu(self):
        sales, sms = self.menus()
        for name in ('sms:reminders', 'sms:log', 'sms:balance'):
            self.assertIn(reverse(name), sms, name)
            self.assertNotIn(reverse(name), sales, name)

    @override_settings(WHATSAPP_ENABLED=True)
    def test_whatsapp_is_in_the_sms_menu_when_it_is_switched_on(self):
        sales, sms = self.menus()
        self.assertIn(reverse('sms:whatsapp-invoices'), sms)
        self.assertNotIn(reverse('sms:whatsapp-invoices'), sales)

    def test_the_sales_menu_keeps_its_own_items(self):
        sales, _ = self.menus()
        for name in ('sales:list', 'sales:invoice-list', 'sales:payment-list', 'installments:list', 'sales:reference-list'):
            self.assertIn(reverse(name), sales, name)
