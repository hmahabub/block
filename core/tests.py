from django.test import SimpleTestCase

from core.templatetags.core_tags import taka_words


class TakaWordsTests(SimpleTestCase):
    def test_zero(self):
        self.assertEqual(taka_words(0), 'Taka Zero Only')

    def test_hundreds_and_teens(self):
        self.assertEqual(taka_words(101), 'Taka One Hundred One Only')
        self.assertEqual(taka_words(15), 'Taka Fifteen Only')

    def test_lakh_and_crore_grouping(self):
        self.assertEqual(taka_words(5_000_000), 'Taka Fifty Lakh Only')
        self.assertEqual(taka_words(16_000_000), 'Taka One Crore Sixty Lakh Only')
        self.assertEqual(taka_words(1_234_567), 'Taka Twelve Lakh Thirty Four Thousand Five Hundred Sixty Seven Only')

    def test_large_crore_counts(self):
        self.assertEqual(taka_words(1_500_000_000), 'Taka One Hundred Fifty Crore Only')

    def test_paisa(self):
        self.assertEqual(taka_words('2000.50'), 'Taka Two Thousand and Fifty Paisa Only')

    def test_decimal_string_from_db(self):
        self.assertEqual(taka_words('16000000.00'), 'Taka One Crore Sixty Lakh Only')


import io
import shutil
import tempfile

from django.conf import settings
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory, TestCase, override_settings
from PIL import Image as PILImage
from reportlab.platypus import Paragraph

from core.forms import CompanyProfileForm
from core.letterhead import letterhead_flowables
from core.models import CompanyProfile

TEMP_MEDIA = tempfile.mkdtemp(prefix='block-test-media-')


def image_file(name='head.png', fmt='PNG', size=(1000, 200)):
    buffer = io.BytesIO()
    PILImage.new('RGB', size, (11, 61, 58)).save(buffer, fmt)
    return SimpleUploadedFile(name, buffer.getvalue(), content_type=f'image/{fmt.lower()}')


@override_settings(MEDIA_ROOT=TEMP_MEDIA)
class CompanyProfileTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEMP_MEDIA, ignore_errors=True)

    def save_profile(self, instance=None, files=None, **data):
        form = CompanyProfileForm(data=data, files=files or {}, instance=instance)
        self.assertTrue(form.is_valid(), form.errors)
        return form.save()

    def test_falls_back_to_settings_when_nothing_saved(self):
        profile = CompanyProfile.current()
        self.assertEqual(profile.display_name, settings.COMPANY_NAME)
        self.assertIsNone(profile.letterhead_url)

    def test_saved_details_override_settings(self):
        self.save_profile(name='Noor Builders', address='Dhaka', phone='0171')
        profile = CompanyProfile.current()
        self.assertEqual((profile.display_name, profile.display_address, profile.display_phone), ('Noor Builders', 'Dhaka', '0171'))

    def test_uploaded_letterhead_is_available(self):
        profile = self.save_profile(files={'letterhead': image_file()})
        self.assertTrue(profile.letterhead_path)
        self.assertTrue(profile.letterhead_url.endswith('.png'))

    def test_rejects_non_image_uploads(self):
        fake = SimpleUploadedFile('head.png', b'not really an image', content_type='image/png')
        form = CompanyProfileForm(data={}, files={'letterhead': fake})
        self.assertFalse(form.is_valid())
        self.assertIn('letterhead', form.errors)

    def test_rejects_unsupported_image_formats(self):
        form = CompanyProfileForm(data={}, files={'letterhead': image_file('head.gif', 'GIF')})
        self.assertFalse(form.is_valid())
        self.assertIn('PNG or JPG', str(form.errors['letterhead']))

    def test_rejects_oversized_images(self):
        big = image_file()
        big.size = 6 * 1024 * 1024
        form = CompanyProfileForm(data={}, files={'letterhead': big})
        self.assertFalse(form.is_valid())
        self.assertIn('5 MB', str(form.errors['letterhead']))

    def test_replacing_the_letterhead_deletes_the_old_file(self):
        import os
        profile = self.save_profile(files={'letterhead': image_file('one.png')})
        old_path = profile.letterhead_path
        profile = self.save_profile(instance=profile, files={'letterhead': image_file('two.png')})
        self.assertFalse(os.path.exists(old_path))
        self.assertTrue(os.path.exists(profile.letterhead_path))

    def test_clearing_removes_the_letterhead_file(self):
        import os
        profile = self.save_profile(files={'letterhead': image_file()})
        path = profile.letterhead_path
        profile = self.save_profile(instance=profile, **{'letterhead-clear': 'on'})
        self.assertFalse(profile.letterhead)
        self.assertFalse(os.path.exists(path))

    def test_missing_file_falls_back_instead_of_breaking(self):
        import os
        profile = self.save_profile(files={'letterhead': image_file()})
        os.remove(profile.letterhead_path)
        self.assertIsNone(CompanyProfile.current().letterhead_url)

    def test_pdf_helper_uses_image_when_present_and_text_otherwise(self):
        style = None
        from reportlab.lib.styles import getSampleStyleSheet
        style = getSampleStyleSheet()['Title']
        flowables, _ = letterhead_flowables(500, style, style)
        self.assertTrue(all(isinstance(f, Paragraph) for f in flowables))

        self.save_profile(files={'letterhead': image_file()})
        flowables, _ = letterhead_flowables(500, style, style)
        self.assertEqual(len(flowables), 1)
        self.assertFalse(isinstance(flowables[0], Paragraph))
        self.assertAlmostEqual(flowables[0].drawWidth, 500)
        self.assertAlmostEqual(flowables[0].drawHeight, 100)  # keeps the 5:1 aspect ratio

    def test_tall_letterheads_are_capped_in_height(self):
        from reportlab.lib.styles import getSampleStyleSheet
        from core.letterhead import MAX_LETTERHEAD_HEIGHT
        style = getSampleStyleSheet()['Title']
        self.save_profile(files={'letterhead': image_file(size=(400, 400))})
        image = letterhead_flowables(500, style, style)[0][0]
        self.assertAlmostEqual(image.drawHeight, MAX_LETTERHEAD_HEIGHT)
        self.assertAlmostEqual(image.drawWidth, MAX_LETTERHEAD_HEIGHT)

    def test_both_pdf_reports_embed_the_letterhead(self):
        from costing.models import CostCategory, ProjectCost
        from costing.views import ProjectCostReportPDFView
        from projects.models import Project
        from reports.views import FinanceReportView

        user = User.objects.create_superuser('admin', 'a@example.com', 'pw')
        project = Project.objects.create(project_name='P')
        ProjectCost.objects.create(project=project, cost_category=CostCategory.objects.create(name='C'), date='2026-01-01', amount=5)

        def costs_pdf():
            request = RequestFactory().get('/')
            request.user = user
            return ProjectCostReportPDFView.as_view()(request).content

        def flats_pdf():
            request = RequestFactory().get('/', {'format': 'pdf'})
            request.user = user
            return FinanceReportView.as_view()(request).content

        self.assertNotIn(b'/Subtype /Image', costs_pdf())
        self.assertNotIn(b'/Subtype /Image', flats_pdf())
        self.save_profile(files={'letterhead': image_file()})
        self.assertIn(b'/Subtype /Image', costs_pdf())
        self.assertIn(b'/Subtype /Image', flats_pdf())


from django.core.management import call_command
from django.core.management.base import CommandError
from django.db.models import Sum


class SeedDemoDataTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command('seed_demo_data')

    def test_two_towers_of_12_floors_and_4_flats_each(self):
        from projects.models import Flat, Project
        self.assertEqual(sorted(Project.objects.values_list('project_name', flat=True)), ['Tower 1', 'Tower 2'])
        for project in Project.objects.all():
            self.assertEqual(project.floor_no, 12)
            self.assertEqual(project.flats.count(), 48)
            self.assertEqual(project.total_saleable_area, 48 * 1700)
            for floor in range(1, 13):
                self.assertEqual(project.flats.filter(floor_no=floor).count(), 4)
            self.assertEqual(sorted({f.unit for f in project.flats.all()}), ['A', 'B', 'C', 'D'])
        self.assertEqual(Flat.objects.values('flat_no', 'project').distinct().count(), 96)
        self.assertTrue(Flat.objects.filter(flat_no='A1', parking_lot='P-A1').exists())

    def test_flat_specifications_are_set_once_on_the_project(self):
        from projects.models import Project
        for project in Project.objects.all():
            self.assertEqual((project.flat_area, project.parking_area, project.bedrooms, project.bathrooms), (1700, 120, 4, 4))
            self.assertGreater(project.quoted_price, project.base_price)
            for room in ('Drawing', 'Dining', 'Balcony'):
                self.assertIn(room, project.features)

    def test_four_customers_and_six_bookings_across_both_towers(self):
        from customers.models import Customer
        from projects.models import Flat
        from sales.models import FlatSale
        self.assertEqual(Customer.objects.count(), 4)
        self.assertEqual(FlatSale.objects.count(), 6)
        self.assertEqual(FlatSale.objects.values('customer').distinct().count(), 4)
        self.assertEqual(Flat.objects.filter(status=Flat.Status.BOOKED).count(), 6)
        self.assertEqual(FlatSale.objects.filter(flat__project__project_name='Tower 1').count(), 3)
        self.assertEqual(FlatSale.objects.filter(flat__project__project_name='Tower 2').count(), 3)
        self.assertEqual(
            sorted(FlatSale.objects.values_list('flat__flat_no', flat=True)), ['A1', 'B2', 'B4', 'C5', 'C8', 'D12'],
        )

    def test_customers_have_the_new_profile_fields(self):
        from customers.models import Customer
        for customer in Customer.objects.all():
            self.assertTrue(customer.phone.startswith('+88'))
            self.assertTrue(customer.title and customer.whatsapp_no and customer.tin and customer.emergency_contact_name)

    def test_initial_payments_per_tower(self):
        from sales.models import FlatSale
        for sale in FlatSale.objects.select_related('flat__project'):
            expected = 2_300_000 if sale.flat.project.project_name == 'Tower 1' else 2_100_000
            self.assertEqual(sale.received_amount, expected)
            self.assertEqual(sale.status, FlatSale.Status.BOOKED)
            self.assertEqual(sale.receivable_amount, sale.net_value - expected)
            self.assertGreaterEqual(sale.sale_value, sale.total_base_price)

    def test_money_is_collected_into_accounts(self):
        from books.ledger import collect_entries, unassigned_count
        from books.models import Account
        self.assertEqual(sorted(Account.objects.values_list('name', flat=True)), ['Bank 1', 'Bank 2', 'Petty cash'])
        self.assertEqual(unassigned_count(), 0)
        self.assertGreater(len(collect_entries()), 12)

    def test_total_cost_is_15_million_and_budget_5_million_each(self):
        from costing.models import ProjectCost
        from projects.models import Project
        self.assertEqual(ProjectCost.objects.aggregate(t=Sum('amount'))['t'], 15_000_000)
        for project in Project.objects.all():
            self.assertEqual(project.total_cost, 7_500_000)
            self.assertEqual(project.pre_development_cost, 4_000_000)
            self.assertEqual(project.post_development_cost, 3_500_000)
            self.assertEqual(project.budget_amount, 5_000_000)

    def test_refuses_to_run_twice(self):
        with self.assertRaises(CommandError):
            call_command('seed_demo_data')


import re
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

from block.settings import _clean_hosts


class AllowedHostsConfigTests(SimpleTestCase):
    def test_spaces_and_empty_entries_are_ignored(self):
        self.assertEqual(_clean_hosts(['example.com', ' www.example.com', ' ', '']), ['example.com', 'www.example.com'])

    def test_quotes_around_names_are_ignored(self):
        hosts = ['localhost', "'asgroupbd.com'", ' "daj.asgroupbd.com" ', "'www.daj.asgroupbd.com'", '']
        self.assertEqual(_clean_hosts(hosts), ['localhost', 'asgroupbd.com', 'daj.asgroupbd.com', 'www.daj.asgroupbd.com'])

    def test_a_lone_pair_of_quotes_counts_as_empty(self):
        self.assertEqual(_clean_hosts(["''", '""']), [])

    def test_wildcards_and_leading_dot_are_kept(self):
        self.assertEqual(_clean_hosts(['.example.com', '*', '192.168.1.5']), ['.example.com', '*', '192.168.1.5'])

    def test_urls_are_rejected_with_a_helpful_message(self):
        for bad in ('https://example.com', 'example.com/', 'http://example.com/app'):
            with self.assertRaisesMessage(ImproperlyConfigured, 'bare domain'):
                _clean_hosts([bad])

    def test_empty_means_no_hosts(self):
        self.assertEqual(_clean_hosts([]), [])


class EnvExampleTests(SimpleTestCase):
    def test_every_setting_read_from_the_environment_is_documented(self):
        root = Path(__file__).resolve().parent.parent
        settings_source = (root / 'block' / 'settings.py').read_text(encoding='utf-8')
        example = (root / '.env.example').read_text(encoding='utf-8')
        names = set(re.findall(r"\benv(?:\.\w+)?\(\s*'([A-Z_]+)'", settings_source))
        self.assertIn('ALLOWED_HOSTS', names)  # guards the regex itself
        for name in sorted(names):
            self.assertRegex(example, rf'(?m)^#?\s*{name}=', f'{name} is missing from .env.example')


import time

from django.contrib.auth.models import AnonymousUser
from django.urls import resolve

from core import reauth
from core.testing import make_request, unlock_client
from core.views import ConfirmPasswordView


class ReauthMiddlewareTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('clerk', password='right-pass')
        self.middleware = reauth.ReauthMiddleware(lambda request: None)

    def check(self, path, session=None, user='default'):
        request = make_request(self.user if user == 'default' else user, path, session=session)
        request.resolver_match = resolve(path)
        return self.middleware.process_view(request, None, (), {}), request

    def test_sensitive_screens_redirect_to_confirm_page_with_next(self):
        response, _ = self.check('/costing/')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], '/confirm-password/?next=%2Fcosting%2F')

    def test_every_default_sensitive_area_is_guarded(self):
        for path in ('/costing/', '/books/', '/reports/'):
            response, _ = self.check(path)
            self.assertIsNotNone(response, path)

    def test_other_screens_are_not_guarded(self):
        for path in ('/', '/customers/', '/projects/', '/sales/'):
            self.assertIsNone(self.check(path)[0], path)

    def test_anonymous_users_are_left_to_the_login_check(self):
        self.assertIsNone(self.check('/costing/', user=AnonymousUser())[0])

    def test_unlocked_session_passes_and_the_window_slides(self):
        soon = time.time() + 30
        response, request = self.check('/costing/', session={'reauth_until': soon})
        self.assertIsNone(response)
        self.assertGreater(request.session['reauth_until'], soon + 60)

    def test_expired_unlock_asks_again(self):
        response, _ = self.check('/costing/', session={'reauth_until': time.time() - 1})
        self.assertEqual(response.status_code, 302)

    def test_lock_clears_the_unlock(self):
        request = make_request(self.user, session={'reauth_until': time.time() + 600})
        reauth.lock(request)
        self.assertFalse(reauth.is_unlocked(request))

    def test_pdf_endpoint_is_unreachable_until_unlocked(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get('/costing/report/pdf/').status_code, 302)
        unlock_client(self.client)
        # Past the lock: the user still lacks nothing here, the report view itself just needs a login.
        self.assertEqual(self.client.get('/costing/report/pdf/').status_code, 200)


class ConfirmPasswordViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('clerk', password='right-pass')

    def post(self, password, next_url='/costing/', session=None):
        request = make_request(self.user, '/confirm-password/', 'post',
                               {'password': password, 'next': next_url}, session=session)
        return ConfirmPasswordView.as_view()(request), request

    def test_right_password_unlocks_and_goes_to_next(self):
        response, request = self.post('right-pass')
        self.assertEqual((response.status_code, response['Location']), (302, '/costing/'))
        self.assertTrue(reauth.is_unlocked(request))

    def test_wrong_password_stays_locked_and_shows_error(self):
        response, request = self.post('nope')
        self.assertEqual(response.status_code, 200)
        response.render()
        self.assertIn('not correct', response.content.decode())
        self.assertFalse(reauth.is_unlocked(request))

    def test_five_wrong_passwords_sign_the_user_out(self):
        session = {'reauth_failures': 4}
        response, _ = self.post('nope', session=session)
        self.assertEqual((response.status_code, response['Location']), (302, '/login/'))

    def test_external_next_urls_are_ignored(self):
        response, _ = self.post('right-pass', next_url='https://evil.example/steal')
        self.assertEqual(response['Location'], '/')

    def test_a_successful_confirm_through_the_real_url_works_end_to_end(self):
        self.client.force_login(self.user)
        response = self.client.post('/confirm-password/', {'password': 'right-pass', 'next': '/costing/report/pdf/'})
        self.assertEqual(response['Location'], '/costing/report/pdf/')
        self.assertEqual(self.client.get('/costing/report/pdf/').status_code, 200)
