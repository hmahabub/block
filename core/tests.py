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
        from reports.views import FlatWisePDFView

        user = User.objects.create_superuser('admin', 'a@example.com', 'pw')
        project = Project.objects.create(project_name='P', total_saleable_area=100)
        ProjectCost.objects.create(project=project, cost_category=CostCategory.objects.create(name='C'), date='2026-01-01', amount=5)

        def costs_pdf():
            request = RequestFactory().get('/')
            request.user = user
            return ProjectCostReportPDFView.as_view()(request).content

        def flats_pdf():
            request = RequestFactory().get('/')
            request.user = user
            return FlatWisePDFView.as_view()(request, project_pk=project.pk).content

        self.assertNotIn(b'/Subtype /Image', costs_pdf())
        self.assertNotIn(b'/Subtype /Image', flats_pdf())
        self.save_profile(files={'letterhead': image_file()})
        self.assertIn(b'/Subtype /Image', costs_pdf())
        self.assertIn(b'/Subtype /Image', flats_pdf())
