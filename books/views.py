import datetime

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.utils import timezone
from django.views import View
from django.views.generic import CreateView, DeleteView, ListView, TemplateView, UpdateView

from core.mixins import CreateAuditMixin, DeleteAuditMixin, UpdateAuditMixin

from .forms import AccountForm, TransferForm
from .ledger import (
    ZERO,
    account_summaries,
    collect_entries,
    confirmable_model,
    unassigned_count,
    with_running_balance,
)
from .models import Account, Transfer


def _parse_date(value):
    try:
        return datetime.date.fromisoformat(value) if value else None
    except ValueError:
        return None


class AccountListView(LoginRequiredMixin, TemplateView):
    template_name = 'books/account_list.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        rows = account_summaries(Account.objects.all())
        context['rows'] = rows
        context['total_confirmed'] = sum((r['confirmed_balance'] for r in rows if r['account'].is_active), ZERO)
        context['total_book'] = sum((r['book_balance'] for r in rows if r['account'].is_active), ZERO)
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
    """The one book: every account together, or a single account with a running balance."""

    template_name = 'books/book.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        params = self.request.GET
        today = timezone.localdate()
        accounts = list(Account.objects.all())

        account_id = self.kwargs.get('pk') or params.get('account')
        account = next((a for a in accounts if str(a.pk) == str(account_id)), None)
        only_unassigned = params.get('account') == 'none'

        date_from = _parse_date(params.get('date_from')) or today.replace(day=1)
        date_to = _parse_date(params.get('date_to')) or today
        status = params.get('status') if params.get('status') in ('confirmed', 'unconfirmed') else ''

        if only_unassigned:
            all_entries = collect_entries(unassigned=True)
            opening = ZERO
        else:
            selected = [account] if account else accounts
            all_entries = collect_entries(selected)
            opening = account.opening_balance if account else sum((a.opening_balance for a in accounts), ZERO)

        # Running balance is computed over the whole history so the opening line of a period is right.
        before = [e for e in all_entries if e.date < date_from]
        period = [e for e in all_entries if date_from <= e.date <= date_to]
        period_opening = opening + sum((e.money_in - e.money_out for e in before), ZERO)
        closing = with_running_balance(period, period_opening)
        if status:
            period = [e for e in period if e.confirmed == (status == 'confirmed')]

        context.update({
            'accounts': accounts,
            'account': account,
            'only_unassigned': only_unassigned,
            'entries': period,
            'opening_balance': period_opening,
            'closing_balance': closing,
            'total_in': sum((e.money_in for e in period), ZERO),
            'total_out': sum((e.money_out for e in period), ZERO),
            'unconfirmed_count': sum(1 for e in period if not e.confirmed),
            'date_from': date_from,
            'date_to': date_to,
            'status': status,
            'can_confirm': self.request.user.has_perm('books.confirm_entries'),
            'unassigned': 0 if only_unassigned else unassigned_count(),
        })
        return context


class ConfirmEntriesView(LoginRequiredMixin, View):
    """Confirm (or un-confirm) the ticked book lines. Needs the books.confirm_entries permission."""

    http_method_names = ['post']

    def post(self, request):
        if not request.user.has_perm('books.confirm_entries'):
            raise PermissionDenied
        undo = request.POST.get('action') == 'unconfirm'
        done = 0
        seen = set()
        for key in request.POST.getlist('entries'):
            if key in seen:
                continue
            seen.add(key)
            kind, _, pk = key.partition(':')
            model = confirmable_model(kind)
            if model is None or not pk.isdigit():
                continue
            item = model.objects.filter(pk=pk).first()
            if item is None:
                continue
            item.unconfirm() if undo else item.confirm(request.user)
            done += 1
        if done:
            messages.success(request, f'{done} entr{"y" if done == 1 else "ies"} {"un-confirmed" if undo else "confirmed"}.')
        else:
            messages.warning(request, 'Tick at least one entry first.')
        target = request.POST.get('next') or ''
        if not target.startswith('/') or target.startswith('//'):
            target = reverse_lazy('books:book')
        return redirect(target)


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
            messages.error(request, 'A confirmed transfer cannot be deleted. Un-confirm it in the book first.')
            return redirect('books:transfers')
        return super().dispatch(request, *args, **kwargs)

    @staticmethod
    def get_object_or_none(pk):
        return Transfer.objects.filter(pk=pk, confirmed_at__isnull=False).first()
