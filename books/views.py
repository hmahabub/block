import datetime

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.shortcuts import redirect
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views import View
from django.views.generic import CreateView, DeleteView, ListView, TemplateView, UpdateView

from core.formatting import DATE, MONEY
from core.mixins import CreateAuditMixin, DeleteAuditMixin, UpdateAuditMixin
from core.utils import int_or_none
from reports.excel import XLSX_CONTENT_TYPE, build_xlsx
from reports.tables import Column, ReportTable

from .forms import AccountForm, TransferForm
from .ledger import (
    ZERO,
    account_summaries,
    assign_account,
    collect_entries,
    confirm_entries,
    unassigned_count,
    with_running_balance,
)
from .models import Account, Transfer


def _parse_date(value):
    try:
        return datetime.date.fromisoformat(value) if value else None
    except ValueError:
        return None


def pick_account(accounts, requested):
    """The account asked for, else the first active one, else the first of all. The book shows one at a time."""
    requested = int_or_none(requested)
    for account in accounts:
        if account.pk == requested:
            return account
    return next((a for a in accounts if a.is_active), accounts[0] if accounts else None)


class AccountListView(LoginRequiredMixin, TemplateView):
    template_name = 'books/account_list.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        rows = account_summaries(Account.objects.all())
        context['rows'] = rows
        context['total_balance'] = sum((r['balance'] for r in rows if r['account'].is_active), ZERO)
        context['total_pending'] = sum(r['pending_count'] for r in rows)
        context['unassigned'] = unassigned_count()
        return context


class AccountCreateView(PermissionRequiredMixin, CreateAuditMixin, CreateView):
    model = Account
    form_class = AccountForm
    template_name = 'books/account_form.html'
    success_url = reverse_lazy('books:accounts')
    permission_required = 'books.add_account'


class AccountUpdateView(PermissionRequiredMixin, UpdateAuditMixin, UpdateView):
    model = Account
    form_class = AccountForm
    template_name = 'books/account_form.html'
    success_url = reverse_lazy('books:accounts')
    permission_required = 'books.change_account'


class BookView(LoginRequiredMixin, TemplateView):
    """The book of ONE account at a time. Only confirmed entries are in it; ?format=xlsx downloads it as Excel."""

    template_name = 'books/book.html'

    def book(self):
        params = self.request.GET
        today = timezone.localdate()
        accounts = list(Account.objects.all())
        account = pick_account(accounts, self.kwargs.get('pk') or params.get('account'))
        date_from = _parse_date(params.get('date_from')) or today.replace(day=1)
        date_to = _parse_date(params.get('date_to')) or today

        entries, opening, closing = [], ZERO, ZERO
        if account:
            confirmed = collect_entries([account], confirmed=True)
            before = [e for e in confirmed if e.date < date_from]
            entries = [e for e in confirmed if date_from <= e.date <= date_to]
            opening = account.opening_balance + sum((e.money_in - e.money_out for e in before), ZERO)
            closing = with_running_balance(entries, opening)
        return {
            'accounts': accounts, 'account': account, 'entries': entries, 'opening_balance': opening,
            'closing_balance': closing, 'date_from': date_from, 'date_to': date_to,
            'total_in': sum((e.money_in for e in entries), ZERO),
            'total_out': sum((e.money_out for e in entries), ZERO),
        }

    def get(self, request, *args, **kwargs):
        book = self.book()
        if request.GET.get('format') == 'xlsx' and book['account']:
            return self.excel(book)
        context = self.get_context_data(**kwargs)
        context.update(book)
        context['pending_count'] = account_summaries([book['account']])[0]['pending_count'] if book['account'] else 0
        context['can_confirm'] = request.user.has_perm('books.confirm_entries')
        return self.render_to_response(context)

    def excel(self, book):
        account = book['account']
        rows = [[book['date_from'], '', 'Opening balance', '', None, None, book['opening_balance']]]
        rows += [[e.date, e.reference, e.source, e.description, e.money_in or None, e.money_out or None, e.balance]
                 for e in book['entries']]
        table = ReportTable(
            f'Book - {account.name}',
            [Column('Date', DATE), Column('Ref.'), Column('Source'), Column('Particulars'),
             Column('In', MONEY), Column('Out', MONEY), Column('Balance', MONEY)],
            rows, ['Total', '', '', '', book['total_in'], book['total_out'], book['closing_balance']],
            note='Only confirmed entries are in the book.',
        )
        lines = [f'Account: {account.name} ({account.detail})', f'Period: {book["date_from"]:%d %b %Y} to {book["date_to"]:%d %b %Y}']
        response = HttpResponse(content_type=XLSX_CONTENT_TYPE)
        response['Content-Disposition'] = f'attachment; filename="book_{account.pk}_{book["date_from"]}_{book["date_to"]}.xlsx"'
        build_xlsx(response, 'Book', lines, [table], self.request.user)
        return response


class ConfirmPageView(PermissionRequiredMixin, TemplateView):
    """Where entries are checked and confirmed, one account at a time. Confirmed entries then appear in the book."""

    template_name = 'books/confirm_entries.html'
    permission_required = 'books.confirm_entries'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        accounts = list(Account.objects.all())
        summaries = {row['account'].pk: row for row in account_summaries(accounts)}
        requested = self.request.GET.get('account')
        if not requested:  # open on the first account that has something waiting
            requested = next((a.pk for a in accounts if summaries[a.pk]['pending_count']), None)
        account = pick_account(accounts, requested)
        context.update({
            'accounts': accounts,
            'account': account,
            'pending': {pk: row['pending_count'] for pk, row in summaries.items()},
            'entries': collect_entries([account], confirmed=False) if account else [],
            'balance': summaries[account.pk]['balance'] if account else ZERO,
            'unassigned_entries': collect_entries(unassigned=True),
            'active_accounts': [a for a in accounts if a.is_active],
        })
        return context


def _safe_next(request, fallback):
    target = request.POST.get('next') or ''
    if target and url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}):
        return target
    return fallback


class ConfirmEntriesView(LoginRequiredMixin, View):
    """Confirm the ticked entries. A confirmation is final, and one that would take an account below zero is refused."""

    http_method_names = ['post']

    def post(self, request):
        if not request.user.has_perm('books.confirm_entries'):
            raise PermissionDenied
        done, problems = confirm_entries(request.POST.getlist('entries'), request.user)
        if done:
            messages.success(
                request, f'{len(done)} entr{"y" if len(done) == 1 else "ies"} confirmed and added to the book. This cannot be undone.',
            )
        elif not problems:
            messages.warning(request, 'Tick at least one entry first.')
        for problem in problems:
            messages.error(request, problem)
        return redirect(_safe_next(request, reverse('books:to-confirm')))


class AssignAccountView(LoginRequiredMixin, View):
    """Give an account to older records made before accounts existed, so they can be confirmed."""

    http_method_names = ['post']

    def post(self, request):
        if not request.user.has_perm('books.confirm_entries'):
            raise PermissionDenied
        account = Account.objects.filter(pk=int_or_none(request.POST.get('account')), is_active=True).first()
        keys = request.POST.getlist('entries')
        if account is None or not keys:
            messages.warning(request, 'Tick the records and choose an account.')
        else:
            count = assign_account(keys, account)
            messages.success(request, f'{count} record(s) now belong to {account.name}. They are waiting to be confirmed.')
        return redirect(_safe_next(request, reverse('books:to-confirm')))


class TransferListView(LoginRequiredMixin, ListView):
    model = Transfer
    template_name = 'books/transfer_list.html'
    context_object_name = 'object_list'
    paginate_by = 50

    def get_queryset(self):
        return super().get_queryset().select_related('from_account', 'to_account')


class TransferCreateView(PermissionRequiredMixin, CreateAuditMixin, CreateView):
    model = Transfer
    form_class = TransferForm
    template_name = 'books/transfer_form.html'
    success_url = reverse_lazy('books:transfers')
    permission_required = 'books.add_transfer'


class TransferDeleteView(PermissionRequiredMixin, DeleteAuditMixin, DeleteView):
    model = Transfer
    template_name = 'books/transfer_confirm_delete.html'
    success_url = reverse_lazy('books:transfers')
    permission_required = 'books.delete_transfer'

    def dispatch(self, request, *args, **kwargs):
        if request.user.has_perm(self.permission_required) and self.get_object_or_none(kwargs['pk']):
            messages.error(request, 'A confirmed transfer is in the book and cannot be deleted.')
            return redirect('books:transfers')
        return super().dispatch(request, *args, **kwargs)

    @staticmethod
    def get_object_or_none(pk):
        return Transfer.objects.filter(pk=pk, confirmed_at__isnull=False).first()
