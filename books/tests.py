import datetime
from decimal import Decimal

from django.contrib.auth.models import Permission, User
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase

from core.testing import make_account, make_project, make_request
from costing.models import CostCategory, ProjectCost
from customers.models import Customer
from sales.models import CustomerPayment, FlatSale, HonorariumPayment, RefundPayment, Reference

from .forms import TransferForm
from .ledger import account_summaries, collect_entries, unassigned_count, with_running_balance
from .models import Account, Transfer
from .views import BookView, ConfirmEntriesView, TransferDeleteView

D = Decimal


class BookTestCase(TestCase):
    def setUp(self):
        self.project, self.flats = make_project()
        self.bank1 = make_account('Bank 1', opening_balance=10_000)
        self.bank2 = make_account('Bank 2')
        self.cash = make_account('Petty cash', account_type=Account.AccountType.CASH)
        self.customer = Customer.objects.create(name='Rahim', phone='01711111111')
        self.ref = Reference.objects.create(name='Ref')
        self.sale = FlatSale.objects.create(
            flat=self.flats[0], customer=self.customer, sale_date='2026-01-01', sale_value=1500, ref=self.ref,
        )
        self.category = CostCategory.objects.create(name='Civil')

    def pay(self, amount, account=None, date='2026-01-05'):
        return CustomerPayment.objects.create(sale=self.sale, payment_date=date, amount=amount, account=account or self.bank1)

    def spend(self, amount, account=None, date='2026-01-06'):
        return ProjectCost.objects.create(
            project=self.project, cost_category=self.category, date=date, amount=amount, account=account or self.bank1,
        )


class LedgerCollectionTests(BookTestCase):
    def test_every_source_shows_up_in_the_book_with_the_right_direction(self):
        self.pay(1000)
        self.spend(200)
        HonorariumPayment.objects.create(sale=self.sale, date='2026-01-07', amount=100, account=self.bank1)
        self.sale.cancel(50)
        self.sale.save()
        RefundPayment.objects.create(sale=self.sale, date='2026-01-08', amount=300, account=self.bank1)
        Transfer.objects.create(date='2026-01-09', from_account=self.bank1, to_account=self.cash, amount=50)

        by_source = {}
        for entry in collect_entries([self.bank1]):
            by_source.setdefault(entry.source, []).append(entry)
        self.assertEqual(by_source['Payment received'][0].money_in, 1000)
        self.assertEqual(by_source['Cost payment'][0].money_out, 200)
        self.assertEqual(by_source['Honorarium paid'][0].money_out, 100)
        self.assertEqual(by_source['Refund to customer'][0].money_out, 300)
        self.assertEqual(by_source['Transfer out'][0].money_out, 50)
        self.assertNotIn('Transfer in', by_source)

    def test_a_transfer_is_out_of_one_account_and_into_the_other(self):
        Transfer.objects.create(date='2026-01-09', from_account=self.bank1, to_account=self.cash, amount=500)
        out_side = [e for e in collect_entries([self.bank1])]
        in_side = [e for e in collect_entries([self.cash])]
        self.assertEqual((out_side[0].money_out, out_side[0].money_in), (500, 0))
        self.assertEqual((in_side[0].money_in, in_side[0].money_out), (500, 0))
        # Moving money between our own accounts leaves the total unchanged.
        rows = account_summaries(Account.objects.all())
        self.assertEqual(sum(r['book_balance'] - r['opening'] for r in rows), 0)

    def test_transfer_between_the_same_account_is_rejected(self):
        form = TransferForm(data={'date': '2026-01-01', 'from_account': self.bank1.pk, 'to_account': self.bank1.pk, 'amount': '5'})
        self.assertFalse(form.is_valid())
        with self.assertRaises(ValidationError):
            Transfer(from_account=self.bank1, to_account=self.bank1, amount=1, date='2026-01-01').clean()

    def test_entries_are_ordered_by_date(self):
        self.spend(10, date='2026-01-10')
        self.pay(100, date='2026-01-02')
        dates = [e.date for e in collect_entries([self.bank1])]
        self.assertEqual(dates, sorted(dates))

    def test_the_book_holds_no_data_of_its_own(self):
        self.pay(1000)
        before = len(collect_entries())
        self.pay(500)
        self.assertEqual(len(collect_entries()), before + 1)
        # Deleting the source record removes the line: there is no second copy to forget.
        CustomerPayment.objects.first().delete()
        self.assertEqual(len(collect_entries()), before)

    def test_records_without_an_account_are_reported_not_counted(self):
        CustomerPayment.objects.create(sale=self.sale, payment_date='2026-01-05', amount=77)
        ProjectCost.objects.create(project=self.project, cost_category=self.category, date='2026-01-05', amount=11)
        self.assertEqual(unassigned_count(), 2)
        self.assertEqual(collect_entries(), [])
        self.assertEqual(sum(r['book_balance'] for r in account_summaries(Account.objects.all())), 10_000)

    def test_running_balance_starts_from_the_opening_balance(self):
        self.pay(1000, date='2026-01-02')
        self.spend(400, date='2026-01-03')
        entries = collect_entries([self.bank1])
        closing = with_running_balance(entries, self.bank1.opening_balance)
        self.assertEqual([e.balance for e in entries], [11_000, 10_600])
        self.assertEqual(closing, 10_600)


class ConfirmationTests(BookTestCase):
    def test_new_entries_start_unconfirmed(self):
        self.pay(1000)
        self.assertFalse(collect_entries([self.bank1])[0].confirmed)

    def test_confirmed_and_book_balances_differ_until_everything_is_checked(self):
        payment = self.pay(1000)
        self.spend(300)
        summary = account_summaries([self.bank1])[0]
        self.assertEqual((summary['confirmed_balance'], summary['book_balance'], summary['unconfirmed_count']), (10_000, 10_700, 2))
        payment.confirm(User.objects.create_user('checker'))
        summary = account_summaries([self.bank1])[0]
        self.assertEqual((summary['confirmed_balance'], summary['book_balance'], summary['unconfirmed_count']), (11_000, 10_700, 1))

    def test_confirming_does_not_disturb_the_sale_totals(self):
        payment = self.pay(1000)
        before = FlatSale.objects.get(pk=self.sale.pk).received_amount
        payment.confirm(User.objects.create_user('checker'))
        self.assertEqual(FlatSale.objects.get(pk=self.sale.pk).received_amount, before)

    def confirm(self, user, keys, action='confirm'):
        request = make_request(user, '/books/confirm/', 'post', {'entries': keys, 'action': action})
        return ConfirmEntriesView.as_view()(request)

    def test_confirm_view_confirms_each_kind_of_entry(self):
        payment = self.pay(1000)
        cost = self.spend(300)
        transfer = Transfer.objects.create(date='2026-01-09', from_account=self.bank1, to_account=self.cash, amount=5)
        user = User.objects.create_superuser('boss', 'b@example.com', 'pw')
        self.confirm(user, [f'cp:{payment.pk}', f'pc:{cost.pk}', f'tr:{transfer.pk}'])
        for obj in (payment, cost, transfer):
            obj.refresh_from_db()
            self.assertTrue(obj.is_confirmed, obj)
            self.assertEqual(obj.confirmed_by, user)

    def test_confirmations_can_be_undone(self):
        payment = self.pay(1000)
        user = User.objects.create_superuser('boss', 'b@example.com', 'pw')
        self.confirm(user, [f'cp:{payment.pk}'])
        self.confirm(user, [f'cp:{payment.pk}'], action='unconfirm')
        payment.refresh_from_db()
        self.assertFalse(payment.is_confirmed)

    def test_confirming_needs_the_permission(self):
        payment = self.pay(1000)
        clerk = User.objects.create_user('clerk')
        with self.assertRaises(PermissionDenied):
            self.confirm(clerk, [f'cp:{payment.pk}'])
        clerk.user_permissions.add(Permission.objects.get(codename='confirm_entries'))
        self.confirm(User.objects.get(pk=clerk.pk), [f'cp:{payment.pk}'])
        payment.refresh_from_db()
        self.assertTrue(payment.is_confirmed)

    def test_bad_keys_are_ignored(self):
        user = User.objects.create_superuser('boss', 'b@example.com', 'pw')
        response = self.confirm(user, ['zz:1', 'cp:abc', 'cp:99999', 'nonsense'])
        self.assertEqual(response.status_code, 302)

    def test_a_confirmed_transfer_cannot_be_deleted(self):
        transfer = Transfer.objects.create(date='2026-01-09', from_account=self.bank1, to_account=self.cash, amount=5)
        user = User.objects.create_superuser('boss', 'b@example.com', 'pw')
        transfer.confirm(user)
        response = TransferDeleteView.as_view()(make_request(user, '/', 'post'), pk=transfer.pk)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Transfer.objects.filter(pk=transfer.pk).exists())

    def test_an_unconfirmed_transfer_can_be_deleted(self):
        transfer = Transfer.objects.create(date='2026-01-09', from_account=self.bank1, to_account=self.cash, amount=5)
        user = User.objects.create_superuser('boss', 'b@example.com', 'pw')
        TransferDeleteView.as_view()(make_request(user, '/', 'post'), pk=transfer.pk)
        self.assertFalse(Transfer.objects.filter(pk=transfer.pk).exists())


class BookViewTests(BookTestCase):
    def context(self, **params):
        user = User.objects.create_superuser(f'u{User.objects.count()}', 'u@example.com', 'pw')
        view = BookView()
        view.setup(make_request(user, '/books/', data=params))
        view.kwargs = {}
        return view.get_context_data()

    def test_period_totals_and_opening_balance(self):
        self.pay(1000, date='2026-01-05')
        self.spend(250, date='2026-02-05')
        context = self.context(account=self.bank1.pk, date_from='2026-02-01', date_to='2026-02-28')
        self.assertEqual(context['opening_balance'], 11_000)
        self.assertEqual((context['total_in'], context['total_out']), (0, 250))
        self.assertEqual(context['closing_balance'], 10_750)
        self.assertEqual(len(context['entries']), 1)

    def test_all_accounts_view_lists_every_account(self):
        self.pay(100, self.bank1, date='2026-01-05')
        self.pay(200, self.bank2, date='2026-01-05')
        context = self.context(date_from='2026-01-01', date_to='2026-01-31')
        self.assertEqual({e.account for e in context['entries']}, {self.bank1, self.bank2})

    def test_status_filter(self):
        first = self.pay(100, date='2026-01-05')
        self.pay(200, date='2026-01-05')
        first.confirm(User.objects.create_user('checker'))
        base = {'date_from': '2026-01-01', 'date_to': '2026-01-31'}
        self.assertEqual(len(self.context(status='confirmed', **base)['entries']), 1)
        self.assertEqual(len(self.context(status='unconfirmed', **base)['entries']), 1)

    def test_unassigned_entries_can_be_listed(self):
        CustomerPayment.objects.create(sale=self.sale, payment_date=datetime.date.today(), amount=9)
        context = self.context(account='none', date_from='2000-01-01')
        self.assertEqual(len(context['entries']), 1)


class AccountTests(TestCase):
    def test_cash_and_bank_accounts(self):
        cash = make_account('Petty cash', account_type=Account.AccountType.CASH)
        bank = make_account('Bank 1', bank_name='X', account_number='123')
        self.assertTrue(cash.is_cash)
        self.assertEqual((cash.detail, bank.detail), ('Cash', 'X · 123'))

    def test_a_fresh_install_already_has_a_petty_cash_account(self):
        # created by the migration so there is always somewhere to put cash
        self.assertTrue(Account.objects.filter(name='Petty cash', account_type='CASH').exists())
