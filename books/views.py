from datetime import timedelta

from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.db.models import Case, DecimalField, F, Sum, When
from django.urls import reverse_lazy
from django.utils import timezone
from django.views.generic import CreateView, ListView

from core.mixins import CreateAuditMixin

from .forms import BankAccountForm, BankBookForm, CashBookForm
from .models import BankAccount, BankBook, CashBook


class LedgerListMixin:
    """Shared 30-day-window + running-total logic for the Cash/Bank Book list views."""

    def get_date_range(self):
        today = timezone.now().date()
        default_start = today - timedelta(days=30)
        start_date = self.request.GET.get('start_date', default_start)
        end_date = self.request.GET.get('end_date', today)
        return start_date, end_date

    def annotate_totals(self, queryset):
        return queryset.annotate(
            debit_amount=Case(
                When(transaction_type='DEBIT', then=F('amount')), default=0, output_field=DecimalField()
            ),
            credit_amount=Case(
                When(transaction_type='CREDIT', then=F('amount')), default=0, output_field=DecimalField()
            ),
        ).order_by('date', 'id')


class CashBookListView(LoginRequiredMixin, LedgerListMixin, ListView):
    model = CashBook
    template_name = 'books/cashbook_list.html'
    context_object_name = 'transactions'
    paginate_by = 100

    def get_queryset(self):
        start_date, end_date = self.get_date_range()
        queryset = CashBook.objects.filter(date__gte=start_date, date__lte=end_date)
        return self.annotate_totals(queryset)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        start_date, end_date = self.get_date_range()
        context['start_date'] = start_date
        context['end_date'] = end_date
        queryset = self.get_queryset()
        context['total_debit'] = queryset.aggregate(total=Sum('debit_amount'))['total'] or 0
        context['total_credit'] = queryset.aggregate(total=Sum('credit_amount'))['total'] or 0
        last_entry = queryset.last()
        context['last_balance'] = last_entry.current_balance if last_entry else 0
        return context


class CashBookCreateView(PermissionRequiredMixin, CreateAuditMixin, CreateView):
    model = CashBook
    form_class = CashBookForm
    template_name = 'books/cashbook_form.html'
    success_url = reverse_lazy('books:cashbook_list')
    permission_required = 'books.add_cashbook'


class BankBookListView(LoginRequiredMixin, LedgerListMixin, ListView):
    model = BankBook
    template_name = 'books/bankbook_list.html'
    context_object_name = 'transactions'
    paginate_by = 100

    def get_queryset(self):
        account_id = self.request.GET.get('account')
        if not account_id:
            first_account = BankAccount.objects.first()
            account_id = first_account.pk if first_account else None
        self.account_id = account_id
        if not account_id:
            return BankBook.objects.none()
        start_date, end_date = self.get_date_range()
        queryset = BankBook.objects.filter(bank_account_id=account_id, date__gte=start_date, date__lte=end_date)
        return self.annotate_totals(queryset)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        start_date, end_date = self.get_date_range()
        context['start_date'] = start_date
        context['end_date'] = end_date
        context['bank_accounts'] = BankAccount.objects.all()
        context['bank_account'] = BankAccount.objects.filter(pk=self.account_id).first()
        queryset = self.get_queryset()
        context['total_debit'] = queryset.aggregate(total=Sum('debit_amount'))['total'] or 0
        context['total_credit'] = queryset.aggregate(total=Sum('credit_amount'))['total'] or 0
        last_entry = queryset.last()
        context['last_balance'] = last_entry.current_balance if last_entry else 0
        return context


class BankBookCreateView(PermissionRequiredMixin, CreateAuditMixin, CreateView):
    model = BankBook
    form_class = BankBookForm
    template_name = 'books/bankbook_form.html'
    success_url = reverse_lazy('books:bankbook_list')
    permission_required = 'books.add_bankbook'


class BankAccountListView(LoginRequiredMixin, ListView):
    model = BankAccount
    template_name = 'books/bankaccount_list.html'
    context_object_name = 'accounts'


class BankAccountCreateView(PermissionRequiredMixin, CreateAuditMixin, CreateView):
    model = BankAccount
    form_class = BankAccountForm
    template_name = 'books/bankaccount_form.html'
    success_url = reverse_lazy('books:bankaccount_list')
    permission_required = 'books.add_bankaccount'
