"""The training guide is part of the website: a link in the user menu and on the home page."""
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse


class TrainingGuideTests(TestCase):
    def test_a_signed_in_user_can_open_the_guide(self):
        User.objects.create_user('clerk', password='pw')
        self.client.login(username='clerk', password='pw')
        response = self.client.get(reverse('training-guide'))
        self.assertEqual(response.status_code, 200)
        self.assertIn('text/html', response['Content-Type'])
        page = response.content.decode()
        self.assertIn('<title>DAR AL JANNAH Training Guide</title>', page)
        self.assertIn('Selling a flat', page)

    def test_the_guide_comes_in_english_and_bangla(self):
        User.objects.create_user('clerk', password='pw')
        self.client.login(username='clerk', password='pw')
        page = self.client.get(reverse('training-guide')).content.decode()
        self.assertIn('data-l="bn"', page)  # the language switch
        self.assertIn('প্রশিক্ষণ গাইড', page)
        self.assertIn('ফ্ল্যাট বিক্রি', page)
        self.assertEqual(page.count('class="chapter"'), 36)  # 18 chapters in each language

    def test_a_visitor_is_sent_to_sign_in(self):
        response = self.client.get(reverse('training-guide'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login/', response['Location'])

    def test_the_link_is_in_the_user_menu_and_on_the_home_page(self):
        User.objects.create_user('clerk', password='pw')
        self.client.login(username='clerk', password='pw')
        page = self.client.get(reverse('home')).content.decode()
        self.assertGreaterEqual(page.count(reverse('training-guide')), 2)
        self.assertIn('Training guide', page)

    def test_the_guide_holds_no_key_or_password(self):
        from django.conf import settings

        text = (settings.BASE_DIR / 'docs' / 'ERP_Training_Guide.html').read_text(encoding='utf-8').lower()
        for word in ('bearer ', 'api_key=', 'sk-'):
            self.assertNotIn(word, text)
