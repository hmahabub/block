import datetime

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.http import HttpResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.views.generic import CreateView, DeleteView, DetailView, ListView, TemplateView, UpdateView

from core.formatting import DATE, MONEY, PERCENT
from core.mixins import CreateAuditMixin, DeleteAuditMixin, UpdateAuditMixin
from core.utils import int_or_none
from projects.models import Development
from reports.excel import XLSX_CONTENT_TYPE, build_xlsx
from reports.tables import Column, ReportTable

from .forms import DirectorForm, DirectorTransactionForm
from .models import ZERO, Director, DirectorTransaction, capital_figures, totals_for


def _date(value):
    try:
        return datetime.date.fromisoformat(value) if value else None
    except ValueError:
        return None


def statement_rows(director, development=None, date_from=None, date_to=None):
    """A director's transactions oldest first, each with the capital still outstanding in its project afterwards."""
    transactions = director.transactions.select_related('development', 'account').order_by('date', 'id')
    outstanding = {}
    rows = []
    for item in transactions:
        balance = outstanding.get(item.development_id, ZERO)
        if item.kind == item.Kind.INVESTMENT:
            balance += item.amount
        elif item.kind == item.Kind.WITHDRAWAL:
            balance -= item.amount
        outstanding[item.development_id] = balance
        item.capital_after = balance
        rows.append(item)
    if development:
        rows = [r for r in rows if r.development_id == development.pk]
    if date_from:
        rows = [r for r in rows if r.date >= date_from]
    if date_to:
        rows = [r for r in rows if r.date <= date_to]
    return rows


class DirectorListView(LoginRequiredMixin, TemplateView):
    template_name = 'directors/director_list.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        development = Development.objects.filter(pk=int_or_none(self.request.GET.get('development'))).first()
        rows = []
        for director in Director.objects.all():
            figures = totals_for(director, development)
            if development and not any(figures[k] for k in ('invested', 'withdrawn', 'profit_paid')):
                continue
            rows.append({'director': director, **figures})
        context.update({
            'rows': rows, 'developments': Development.objects.all(), 'selected_development': development,
            'grand': totals_for(None, development),
        })
        return context


class DirectorDetailView(LoginRequiredMixin, DetailView):
    model = Director
    template_name = 'directors/director_detail.html'
    context_object_name = 'object'

    def filters(self):
        params = self.request.GET
        return (
            Development.objects.filter(pk=int_or_none(params.get('development'))).first(),
            _date(params.get('date_from')), _date(params.get('date_to')),
        )

    def get(self, request, *args, **kwargs):
        self.object = self.get_object()
        if request.GET.get('format') == 'xlsx':
            return self.excel()
        return self.render_to_response(self.get_context_data(object=self.object))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        development, date_from, date_to = self.filters()
        context.update({
            'project_rows': self.object.project_rows(),
            'overall': self.object.totals(),
            'transactions': list(reversed(statement_rows(self.object, development, date_from, date_to))),
            'developments': Development.objects.all(), 'selected_development': development,
            'date_from': date_from, 'date_to': date_to,
        })
        return context

    def excel(self):
        director = self.object
        development, date_from, date_to = self.filters()
        summary = ReportTable(
            'Summary by project',
            [Column('Project'), Column('Invested', MONEY), Column('Capital withdrawn', MONEY),
             Column('Capital outstanding', MONEY), Column('Returned %', PERCENT), Column('Profit share paid', MONEY)],
            [[r['development'].name, r['invested'], r['withdrawn'], r['outstanding'], r['returned_percent'], r['profit_paid']]
             for r in director.project_rows()],
            ['Total'] + [director.totals()[k] for k in ('invested', 'withdrawn', 'outstanding', 'returned_percent', 'profit_paid')],
        )
        statement = ReportTable(
            'Statement',
            [Column('Date', DATE), Column('Ref.'), Column('Project'), Column('Type'), Column('Account'),
             Column('Invested', MONEY), Column('Withdrawn', MONEY), Column('Capital outstanding', MONEY), Column('Confirmed')],
            [[r.date, r.reference_no, r.development.name, r.get_kind_display(), r.account.name,
              r.amount if r.kind == r.Kind.INVESTMENT else None,
              r.amount if r.kind != r.Kind.INVESTMENT else None, r.capital_after, 'Yes' if r.is_confirmed else 'No']
             for r in statement_rows(director, development, date_from, date_to)],
        )
        response = HttpResponse(content_type=XLSX_CONTENT_TYPE)
        response['Content-Disposition'] = f'attachment; filename="director_{director.director_code}.xlsx"'
        build_xlsx(response, f'Director statement - {director.name}', [f'Director: {director.name} ({director.director_code})'],
                   [summary, statement], self.request.user)
        return response


class DirectorCreateView(PermissionRequiredMixin, CreateAuditMixin, CreateView):
    model = Director
    form_class = DirectorForm
    template_name = 'directors/director_form.html'
    permission_required = 'directors.add_director'


class DirectorUpdateView(PermissionRequiredMixin, UpdateAuditMixin, UpdateView):
    model = Director
    form_class = DirectorForm
    template_name = 'directors/director_form.html'
    permission_required = 'directors.change_director'


class TransactionCreateView(PermissionRequiredMixin, CreateAuditMixin, CreateView):
    model = DirectorTransaction
    form_class = DirectorTransactionForm
    template_name = 'directors/transaction_form.html'
    permission_required = 'directors.add_directortransaction'

    def get_initial(self):
        initial = super().get_initial()
        params = self.request.GET
        director = Director.objects.filter(pk=int_or_none(params.get('director'))).first()
        development = Development.objects.filter(pk=int_or_none(params.get('development'))).first()
        if director:
            initial['director'] = director
        if development:
            initial['development'] = development
        if params.get('kind') in DirectorTransaction.Kind.values:
            initial['kind'] = params['kind']
        return initial

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['outstanding'] = {}
        for director in Director.objects.all():
            for row in director.project_rows():
                context['outstanding'].setdefault(director.pk, {})[row['development'].pk] = str(row['outstanding'])
        return context


class _ConfirmedLock:
    """A transaction confirmed in the books is part of the book: it can be viewed, never changed or deleted."""

    def dispatch(self, request, *args, **kwargs):
        if request.user.has_perm(self.permission_required):
            item = DirectorTransaction.objects.filter(pk=kwargs['pk'], confirmed_at__isnull=False).first()
            if item:
                messages.error(request, f'{item.reference_no} is confirmed in the books and cannot be changed or deleted.')
                return redirect(item.get_absolute_url())
        return super().dispatch(request, *args, **kwargs)


class TransactionUpdateView(_ConfirmedLock, PermissionRequiredMixin, UpdateAuditMixin, UpdateView):
    model = DirectorTransaction
    form_class = DirectorTransactionForm
    template_name = 'directors/transaction_form.html'
    permission_required = 'directors.change_directortransaction'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['outstanding'] = {}
        return context


class TransactionDeleteView(_ConfirmedLock, PermissionRequiredMixin, DeleteAuditMixin, DeleteView):
    model = DirectorTransaction
    template_name = 'directors/transaction_confirm_delete.html'
    permission_required = 'directors.delete_directortransaction'

    def get_success_url(self):
        return reverse('directors:detail', kwargs={'pk': self.object.director_id})

    def form_valid(self, form):
        item = self.object
        if item.kind == item.Kind.INVESTMENT:
            invested, withdrawn = capital_figures(item.director_id, item.development_id, exclude=item.pk)
            if withdrawn > invested:
                messages.error(self.request, 'This investment cannot be deleted: capital has already been withdrawn against it.')
                return redirect(item.get_absolute_url())
        return super().form_valid(form)


class InvestmentSummaryView(LoginRequiredMixin, TemplateView):
    """Per project: how much each director invested, withdrew and still has in; ?format=xlsx downloads it."""

    template_name = 'directors/summary.html'

    def get(self, request, *args, **kwargs):
        if request.GET.get('format') == 'xlsx':
            return self.excel()
        return super().get(request, *args, **kwargs)

    def project_rows(self):
        rows = []
        for development in Development.objects.all():
            figures = totals_for(None, development)
            if any(figures[k] for k in ('invested', 'withdrawn', 'profit_paid')):
                rows.append({'development': development, **figures})
        return rows

    def director_rows(self, development):
        rows = []
        for director in Director.objects.all():
            figures = totals_for(director, development)
            if any(figures[k] for k in ('invested', 'withdrawn', 'profit_paid')):
                rows.append({'director': director, **figures})
        return rows

    def selected(self):
        return Development.objects.filter(pk=int_or_none(self.request.GET.get('development'))).first()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        development = self.selected()
        context.update({
            'project_rows': self.project_rows(), 'selected_development': development,
            'developments': Development.objects.all(), 'grand': totals_for(),
        })
        if development:
            context['director_rows'] = self.director_rows(development)
            context['project_totals'] = totals_for(None, development)
            context['collected'] = development.total_received
        return context

    def excel(self):
        development = self.selected()
        tables = [ReportTable(
            'By project',
            [Column('Project'), Column('Invested', MONEY), Column('Capital withdrawn', MONEY),
             Column('Capital outstanding', MONEY), Column('Returned %', PERCENT), Column('Profit share paid', MONEY)],
            [[r['development'].name, r['invested'], r['withdrawn'], r['outstanding'], r['returned_percent'], r['profit_paid']]
             for r in self.project_rows()],
            ['Total'] + [totals_for()[k] for k in ('invested', 'withdrawn', 'outstanding', 'returned_percent', 'profit_paid')],
        )]
        if development:
            tables.append(ReportTable(
                f'Directors in {development.name}',
                [Column('Director'), Column('Invested', MONEY), Column('Capital withdrawn', MONEY),
                 Column('Capital outstanding', MONEY), Column('Returned %', PERCENT), Column('Profit share paid', MONEY)],
                [[r['director'].name, r['invested'], r['withdrawn'], r['outstanding'], r['returned_percent'], r['profit_paid']]
                 for r in self.director_rows(development)],
            ))
        response = HttpResponse(content_type=XLSX_CONTENT_TYPE)
        response['Content-Disposition'] = 'attachment; filename="director_investments.xlsx"'
        build_xlsx(response, 'Director investments', [f'Project: {development.name}' if development else 'All projects'],
                   tables, self.request.user)
        return response
