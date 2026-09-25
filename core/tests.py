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
