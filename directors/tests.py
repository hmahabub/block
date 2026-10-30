import io
import time
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from openpyxl import load_workbook

from books.ledger import account_summaries, collect_entries, confirm_entries, pending_count
from core.testing import make_account, make_request
from projects.models import Development

from .forms import DirectorForm, DirectorTransactionForm
from .models import Director, DirectorTransaction, capital_figures, totals_for
from .views import (
    DirectorCreateView,
    DirectorDetailView,
    DirectorListView,
    InvestmentSummaryView,
    TransactionCreateView,
    TransactionDeleteView,
    TransactionUpdateView,
)

D = Decimal
UNLOCKED = dict(session={'reauth_until': time.time() + 600, 'reauth_token': 'tok'}, cookies={'daj_unlocked': 'tok'})


class DirectorTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser('boss', 'b@example.com', 'pw')
        self.estate = Development.objects.create(name='Estate One')
        self.other = Development.objects.create(name='Estate Two')
        self.rahim = Director.objects.create(name='Rahim', phone='01711000001')
        self.karim = Director.objects.create(name='Karim')
        self.bank = make_account('Bank 1')

    def tx(self, kind, amount, director=None, development=None, date='2026-01-10', account=None):
        item = DirectorTransaction(
            director=director or self.rahim, development=development or self.estate, kind=kind, date=date,
            amount=D(amount), account=account or self.bank,
        )
        item.full_clean()
        item.save()
        return item

    def invest(self, amount, **kw):
        return self.tx('INVESTMENT', amount, **kw)

    def withdraw(self, amount, **kw):
        return self.tx('WITHDRAWAL', amount, **kw)


class DirectorModelTests(DirectorTestCase):
    def test_codes_and_phone(self):
        self.assertRegex(self.rahim.director_code, r'^[A-Z]+-DIR-\d{3}$')
        self.assertEqual(self.rahim.phone, '+8801711000001')
        self.assertEqual(self.karim.director_code[-3:], '002')

    def test_nid_is_unique_when_given(self):
        Director.objects.create(name='A', identification_no='123')
        Director.objects.create(name='B')
        Director.objects.create(name='C')   # blanks are fine
        with self.assertRaises(IntegrityError), transaction.atomic():
            Director.objects.create(name='D', identification_no='123')
        form = DirectorForm(data={'name': 'E', 'identification_no': ' 123 '})
        self.assertFalse(form.is_valid())
        self.assertIn('identification_no', form.errors)

    def test_totals(self):
        self.invest(1000)
        self.invest(500, date='2026-02-01')
        self.withdraw(300)
        self.tx('PROFIT', 80)
        figures = self.rahim.totals()
        self.assertEqual((figures['invested'], figures['withdrawn'], figures['outstanding'], figures['profit_paid']), (1500, 300, 1200, 80))
        self.assertEqual(figures['returned_percent'], 20)

    def test_totals_are_per_director_and_per_project(self):
        self.invest(1000)
        self.invest(700, director=self.karim)
        self.invest(400, development=self.other)
        self.assertEqual(self.rahim.totals(self.estate)['invested'], 1000)
        self.assertEqual(self.rahim.totals(self.other)['invested'], 400)
        self.assertEqual(self.rahim.totals()['invested'], 1400)
        self.assertEqual(totals_for(None, self.estate)['invested'], 1700)
        self.assertEqual(totals_for()['invested'], 2100)

    def test_a_director_with_nothing_has_zero_and_no_percentage(self):
        figures = self.karim.totals()
        self.assertEqual((figures['invested'], figures['outstanding'], figures['returned_percent']), (0, 0, None))

    def test_project_rows_list_only_projects_with_money(self):
        self.invest(100)
        self.assertEqual([r['development'] for r in self.rahim.project_rows()], [self.estate])


class CapitalRulesTests(DirectorTestCase):
    def test_a_withdrawal_cannot_exceed_what_is_still_invested(self):
        self.invest(1000)
        self.withdraw(600)
        with self.assertRaises(ValidationError) as caught:
            self.withdraw(500)
        self.assertIn('400.00', str(caught.exception))   # only 400 still outstanding
        self.withdraw(400)
        self.assertEqual(self.rahim.totals()['outstanding'], 0)

    def test_money_invested_in_another_project_does_not_count(self):
        self.invest(1000, development=self.other)
        with self.assertRaises(ValidationError):
            self.withdraw(1, development=self.estate)

    def test_one_directors_money_does_not_cover_another(self):
        self.invest(1000, director=self.karim)
        with self.assertRaises(ValidationError):
            self.withdraw(1)

    def test_profit_is_not_limited_by_capital(self):
        self.tx('PROFIT', 5000)
        self.assertEqual(self.rahim.totals()['profit_paid'], 5000)

    def test_an_investment_cannot_be_lowered_below_what_was_withdrawn(self):
        investment = self.invest(1000)
        self.withdraw(700)
        investment.amount = D('600')
        with self.assertRaises(ValidationError):
            investment.full_clean()
        investment.amount = D('700')
        investment.full_clean()

    def test_the_form_applies_the_same_rule(self):
        self.invest(1000)
        data = {'director': self.rahim.pk, 'development': self.estate.pk, 'kind': 'WITHDRAWAL', 'date': '2026-02-01',
                'account': self.bank.pk, 'amount': '1500'}
        form = DirectorTransactionForm(data=data)
        self.assertFalse(form.is_valid())
        self.assertIn('amount', form.errors)
        self.assertTrue(DirectorTransactionForm(data={**data, 'amount': '1000'}).is_valid())

    def test_an_amount_must_be_positive_and_an_account_is_required(self):
        data = {'director': self.rahim.pk, 'development': self.estate.pk, 'kind': 'INVESTMENT', 'date': '2026-02-01', 'amount': '0'}
        form = DirectorTransactionForm(data=data)
        self.assertFalse(form.is_valid())
        self.assertIn('amount', form.errors)
        self.assertIn('account', form.errors)

    def test_capital_figures_can_leave_one_transaction_out(self):
        first = self.invest(1000)
        self.invest(500)
        self.assertEqual(capital_figures(self.rahim.pk, self.estate.pk, exclude=first.pk), (500, 0))

    def test_inactive_directors_are_not_offered_for_new_entries(self):
        self.karim.is_active = False
        self.karim.save()
        offered = list(DirectorTransactionForm().fields['director'].queryset)
        self.assertIn(self.rahim, offered)
        self.assertNotIn(self.karim, offered)


class BookIntegrationTests(DirectorTestCase):
    """Director money goes through the book like every other payment: it waits for confirmation first."""

    def test_an_investment_is_money_in_and_a_withdrawal_money_out(self):
        self.invest(1000)
        self.withdraw(300)
        self.tx('PROFIT', 50)
        entries = {e.source: e for e in collect_entries([self.bank])}
        self.assertEqual(entries['Director investment'].money_in, 1000)
        self.assertEqual(entries['Director capital withdrawal'].money_out, 300)
        self.assertEqual(entries['Director profit share paid'].money_out, 50)

    def test_nothing_is_in_the_book_until_confirmed(self):
        self.invest(1000)
        self.assertEqual(collect_entries([self.bank], confirmed=True), [])
        self.assertEqual(pending_count(), 1)
        item = DirectorTransaction.objects.get()
        done, problems = confirm_entries([f'dt:{item.pk}'], self.user)
        self.assertEqual((done, problems), ([f'dt:{item.pk}'], []))
        self.assertEqual(account_summaries([self.bank])[0]['balance'], 1000)
        self.assertEqual(pending_count(), 0)

    def test_a_withdrawal_cannot_be_confirmed_if_the_account_cannot_cover_it(self):
        self.invest(1000)   # recorded, but the money is not confirmed into the bank yet
        withdrawal = self.withdraw(400)
        done, problems = confirm_entries([f'dt:{withdrawal.pk}'], self.user)
        self.assertEqual(done, [])
        self.assertIn('below zero', problems[0])

    def test_confirming_the_investment_first_lets_the_withdrawal_through(self):
        investment = self.invest(1000)
        withdrawal = self.withdraw(400)
        done, problems = confirm_entries([f'dt:{withdrawal.pk}', f'dt:{investment.pk}'], self.user)
        self.assertEqual((len(done), problems), (2, []))
        self.assertEqual(account_summaries([self.bank])[0]['balance'], 600)

    def test_a_confirmed_transaction_can_no_longer_be_changed_or_deleted(self):
        item = self.invest(1000)
        confirm_entries([f'dt:{item.pk}'], self.user)
        for view in (TransactionUpdateView, TransactionDeleteView):
            response = view.as_view()(make_request(self.user, '/', 'post', {}), pk=item.pk)
            self.assertEqual(response.status_code, 302)
        item.refresh_from_db()
        self.assertEqual(item.amount, 1000)
        self.assertTrue(DirectorTransaction.objects.filter(pk=item.pk).exists())


class DirectorScreenTests(DirectorTestCase):
    def render(self, view, user=None, method='get', data=None, locked=False, **kwargs):
        extra = {} if locked else UNLOCKED
        request = make_request(user or self.user, '/', method, data, **extra)
        response = view.as_view()(request, **kwargs)
        if hasattr(response, 'render'):
            response.render()
        return response

    def test_the_pages_render(self):
        self.invest(1000)
        self.withdraw(200)
        item = DirectorTransaction.objects.first()
        for view, kwargs in ((DirectorListView, {}), (DirectorDetailView, {'pk': self.rahim.pk}), (InvestmentSummaryView, {}),
                             (TransactionCreateView, {}), (TransactionUpdateView, {'pk': item.pk}), (TransactionDeleteView, {'pk': item.pk})):
            response = self.render(view, **kwargs)
            self.assertEqual(response.status_code, 200, view.__name__)

    def test_the_list_shows_each_directors_figures(self):
        self.invest(1000)
        self.withdraw(250)
        html = self.render(DirectorListView).content.decode()
        for expected in ('Rahim', '1,000.00', '250.00', '750.00', '25.0%'):
            self.assertIn(expected, html)

    def test_the_statement_has_a_running_capital_balance(self):
        self.invest(1000, date='2026-01-01')
        self.withdraw(300, date='2026-02-01')
        self.invest(500, date='2026-03-01')
        view = DirectorDetailView()
        view.setup(make_request(self.user, '/'), pk=self.rahim.pk)
        view.kwargs = {'pk': self.rahim.pk}
        view.object = self.rahim
        rows = view.get_context_data(object=self.rahim)['transactions']
        self.assertEqual([r.capital_after for r in rows], [1200, 700, 1000])   # newest first

    def test_the_statement_can_be_filtered_by_project_and_date(self):
        self.invest(1000, date='2026-01-01')
        self.invest(400, development=self.other, date='2026-02-01')
        view = DirectorDetailView()
        view.setup(make_request(self.user, '/', data={'development': self.other.pk}), pk=self.rahim.pk)
        view.kwargs = {'pk': self.rahim.pk}
        view.object = self.rahim
        self.assertEqual([r.amount for r in view.get_context_data(object=self.rahim)['transactions']], [400])

    def test_creating_a_director_and_a_transaction_through_the_views(self):
        response = self.render(DirectorCreateView, method='post', data={'name': 'New Director', 'is_active': 'on'})
        self.assertEqual(response.status_code, 302)
        director = Director.objects.get(name='New Director')
        data = {'director': director.pk, 'development': self.estate.pk, 'kind': 'INVESTMENT', 'date': '2026-03-01',
                'amount': '2500', 'account': self.bank.pk}
        response = self.render(TransactionCreateView, method='post', data=data)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(director.totals()['invested'], 2500)

    def test_the_create_screen_can_be_prefilled(self):
        view = TransactionCreateView()
        view.setup(make_request(self.user, '/', data={'director': self.karim.pk, 'kind': 'WITHDRAWAL', 'development': self.other.pk}))
        initial = view.get_initial()
        self.assertEqual((initial['director'], initial['kind'], initial['development']), (self.karim, 'WITHDRAWAL', self.other))

    def test_only_unconfirmed_transactions_can_be_edited_and_deleted(self):
        item = self.invest(1000)
        data = {'director': self.rahim.pk, 'development': self.estate.pk, 'kind': 'INVESTMENT', 'date': '2026-01-10',
                'amount': '1200', 'account': self.bank.pk}
        self.render(TransactionUpdateView, method='post', data=data, pk=item.pk)
        item.refresh_from_db()
        self.assertEqual(item.amount, 1200)
        self.render(TransactionDeleteView, method='post', pk=item.pk)
        self.assertFalse(DirectorTransaction.objects.filter(pk=item.pk).exists())

    def test_an_investment_with_withdrawals_against_it_cannot_be_deleted(self):
        investment = self.invest(1000)
        self.withdraw(600)
        self.render(TransactionDeleteView, method='post', pk=investment.pk)
        self.assertTrue(DirectorTransaction.objects.filter(pk=investment.pk).exists())

    def test_creating_needs_the_permission(self):
        clerk = User.objects.create_user('clerk')
        with self.assertRaises(PermissionDenied):
            self.render(DirectorCreateView, user=clerk, method='post', data={'name': 'X'})
        with self.assertRaises(PermissionDenied):
            self.render(TransactionCreateView, user=clerk, method='post', data={})

    def test_the_summary_by_project(self):
        self.invest(1000)
        self.invest(300, director=self.karim)
        self.withdraw(100)
        view = InvestmentSummaryView()
        view.setup(make_request(self.user, '/', data={'development': self.estate.pk}))
        view.kwargs = {}
        context = view.get_context_data()
        self.assertEqual([r['development'] for r in context['project_rows']], [self.estate])
        self.assertEqual({r['director'].name: r['outstanding'] for r in context['director_rows']}, {'Rahim': 900, 'Karim': 300})
        self.assertEqual(context['project_totals']['invested'], 1300)

    def test_the_project_page_shows_the_investment_only_when_unlocked(self):
        from projects.views import DevelopmentDetailView
        self.invest(1234)
        unlocked = self.render(DevelopmentDetailView, pk=self.estate.pk).content.decode()
        locked = self.render(DevelopmentDetailView, pk=self.estate.pk, locked=True).content.decode()
        self.assertIn('1,234.00', unlocked)
        self.assertNotIn('1,234.00', locked)

    def test_the_whole_module_is_behind_the_password_prompt(self):
        from django.conf import settings
        self.assertIn('directors', settings.SENSITIVE_NAMESPACES)
        self.assertIn('activity_log', settings.SENSITIVE_NAMESPACES)


class ExcelTests(DirectorTestCase):
    def cells(self, response):
        sheet = load_workbook(io.BytesIO(response.content)).active
        return [c.value for row in sheet.iter_rows() for c in row]

    def test_the_directors_statement_downloads_as_excel(self):
        self.invest(1000)
        self.withdraw(250)
        view = DirectorDetailView()
        request = make_request(self.user, '/', data={'format': 'xlsx'})
        view.setup(request, pk=self.rahim.pk)
        view.kwargs = {'pk': self.rahim.pk}
        response = view.get(request)
        self.assertIn('spreadsheetml', response['Content-Type'])
        cells = self.cells(response)
        for expected in (1000.0, 250.0, 750.0, 'Director statement - Rahim', 'Statement'):
            self.assertIn(expected, cells)

    def test_the_project_summary_downloads_as_excel(self):
        self.invest(1000)
        request = make_request(self.user, '/', data={'format': 'xlsx', 'development': self.estate.pk})
        view = InvestmentSummaryView()
        view.setup(request)
        view.kwargs = {}
        cells = self.cells(view.get(request))
        self.assertIn(1000.0, cells)
        self.assertIn('Estate One', cells)
        self.assertIn('Rahim', cells)
