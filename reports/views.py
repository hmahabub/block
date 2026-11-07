import datetime

from django.contrib.auth.mixins import LoginRequiredMixin
from django.utils import timezone
from django.http import HttpResponse
from django.views.generic import TemplateView

from core.reauth import money_visible
from core.utils import int_or_none
from core.workspace import current_development, in_workspace
from projects.models import Development, Project

from . import builders
from .daily import daily_transactions_report, day_book, parse_day, period_text
from .excel import XLSX_CONTENT_TYPE, build_xlsx
from .costs import daily_cost_report
from .customer_wise import customer_wise_report
from .profitability import profitability_report
from .tables import build_pdf


def _date(value):
    try:
        return datetime.date.fromisoformat(value) if value else None
    except ValueError:
        return None


class ReportIndexView(LoginRequiredMixin, TemplateView):
    template_name = 'reports/index.html'


class ReportView(LoginRequiredMixin, TemplateView):
    """One report, shown as tables on screen; ?format=pdf gives the letterhead PDF and ?format=xlsx an Excel file."""

    template_name = 'reports/report.html'
    title = ''
    description = ''
    phase = ''
    uses_period = False
    pdf_name = 'report'

    def filters(self):
        params = self.request.GET
        project_id = int_or_none(params.get('project'))
        project = in_workspace(Project.objects.all(), self.request, 'development').filter(pk=project_id).first() if project_id else None
        development_id = int_or_none(params.get('development'))
        # Inside a project the report is always about that project.
        development = current_development(self.request) or (
            Development.objects.filter(pk=development_id).first() if development_id else None)
        return {'project': project, 'development': development,
                'date_from': _date(params.get('date_from')), 'date_to': _date(params.get('date_to'))}

    def build(self, filters):
        raise NotImplementedError

    def get(self, request, *args, **kwargs):
        filters = self.filters()
        lines, tables = self.build(filters)
        if request.GET.get('format') == 'pdf':
            response = HttpResponse(content_type='application/pdf')
            response['Content-Disposition'] = f'inline; filename="{self.pdf_name}.pdf"'
            build_pdf(response, self.title, lines, tables, request.user)
            return response
        if request.GET.get('format') == 'xlsx':
            response = HttpResponse(content_type=XLSX_CONTENT_TYPE)
            response['Content-Disposition'] = f'attachment; filename="{self.pdf_name}.xlsx"'
            build_xlsx(response, self.title, lines, tables, request.user)
            return response
        context = self.get_context_data(filters=filters, filter_lines=lines, tables=tables, **kwargs)
        return self.render_to_response(context)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        filters = kwargs['filters']
        context.update({
            'title': self.title, 'description': self.description, 'phase': self.phase,
            'uses_period': self.uses_period, 'projects': in_workspace(Project.objects.all(), self.request, 'development'),
            'developments': Development.objects.all(), 'selected_development': filters['development'],
            'selected_project': filters['project'], 'date_from': filters['date_from'], 'date_to': filters['date_to'],
        })
        return context


class FinanceReportView(ReportView):
    title = 'Finance Report'
    description = 'Sales, cost, receivable and payable across every phase, plus the money in hand.'
    phase = 'All phases'
    pdf_name = 'finance_report'

    def build(self, filters):
        return builders.finance_report(filters['project'], filters['development'])


class PeriodicCollectionReportView(ReportView):
    title = 'Periodic Payment Collection'
    description = 'Customer payments collected, grouped by month, customer and account.'
    phase = 'Pre-development'
    uses_period = True
    pdf_name = 'periodic_collection'

    def build(self, filters):
        return builders.periodic_collection_report(filters['project'], filters['date_from'], filters['date_to'], filters['development'])


class ProfitLossReportView(ReportView):
    title = 'Profit, Loss, Collection and Due'
    description = 'What share sales earn against land, marketing and pre-development cost; what is collected and what is still due.'
    phase = 'Pre-development'
    pdf_name = 'profit_loss_collection_due'

    def build(self, filters):
        return builders.profit_loss_report(filters['project'], filters['development'])


class CustomerPostReportView(ReportView):
    title = 'Customer Balance, Cost, Receivable and Payable'
    description = 'Per customer: balance held, receivable, share of post-development cost and what is payable.'
    phase = 'Post-development'
    pdf_name = 'customer_balance_cost'

    def build(self, filters):
        return builders.customer_post_report(filters['project'], filters['development'])


class FlatWiseReportView(ReportView):
    title = 'Flat-Wise Report'
    description = 'Sale, collection and cost share for each flat.'
    phase = 'All phases'
    pdf_name = 'flat_wise_report'

    def build(self, filters):
        return builders.flat_wise_report(filters['project'], filters['development'])


class DuesReportView(ReportView):
    title = 'Receivables'
    description = 'Outstanding balances still to be collected from customers.'
    phase = 'All phases'
    pdf_name = 'receivables'

    def build(self, filters):
        return builders.dues_report(filters['project'], filters['development'])


class ProfitabilityReportView(ReportView):
    title = 'Profitability Analysis'
    description = 'What the project earns, what it costs, the margin, what it would earn if every flat were sold, and the cash position.'
    phase = 'All phases'
    pdf_name = 'profitability_analysis'

    def build(self, filters):
        return profitability_report(filters['project'], filters['development'])


class DailyTransactionsView(LoginRequiredMixin, TemplateView):
    """Every transaction of a day (or period) in the open project, verified or not, so each day can be checked.

    Entries still waiting can be verified from here (they then enter the book). ?format=pdf or xlsx downloads the day."""

    template_name = 'reports/daily.html'

    def get(self, request, *args, **kwargs):
        development = current_development(request)
        today = timezone.localdate()
        date_from = parse_day(request.GET.get('date_from'), today)
        date_to = parse_day(request.GET.get('date_to'), date_from)
        if date_to < date_from:
            date_from, date_to = date_to, date_from
        if not money_visible(request):
            return self.render_to_response(self.get_context_data(locked=True, date_from=date_from, date_to=date_to))

        book = day_book(development, date_from, date_to)
        fmt = request.GET.get('format')
        if fmt in ('pdf', 'xlsx'):
            lines, tables = daily_transactions_report(development, date_from, date_to, book)
            stamp = f'{development.code}_{date_from:%Y-%m-%d}' + (f'_to_{date_to:%Y-%m-%d}' if date_to != date_from else '')
            if fmt == 'pdf':
                response = HttpResponse(content_type='application/pdf')
                response['Content-Disposition'] = f'inline; filename="daily_transactions_{stamp}.pdf"'
                build_pdf(response, 'Daily Transactions', lines, tables, request.user)
            else:
                response = HttpResponse(content_type=XLSX_CONTENT_TYPE)
                response['Content-Disposition'] = f'attachment; filename="daily_transactions_{stamp}.xlsx"'
                build_xlsx(response, 'Daily Transactions', lines, tables, request.user)
            return response

        one_day = datetime.timedelta(days=1)
        return self.render_to_response(self.get_context_data(
            book=book, date_from=date_from, date_to=date_to, period=period_text(date_from, date_to),
            previous_day=date_from - one_day, next_day=date_to + one_day, today=today,
            can_verify=request.user.has_perm('books.confirm_entries'),
        ))


class DailyCostReportView(ReportView):
    """The costs of a day (today unless another day or a period is chosen), pre-development and post-development apart."""

    title = 'Daily Cost Report'
    description = 'What was spent on the day, pre-development (the company\'s cost) and post-development (shared by the flat owners) apart.'
    phase = 'Pre- and post-development'
    uses_period = True
    pdf_name = 'daily_cost_report'

    def filters(self):
        filters = super().filters()
        start, end = filters['date_from'], filters['date_to']
        if not start and not end:
            start = end = timezone.localdate()
        filters['date_from'], filters['date_to'] = start or end, end or start
        return filters

    def build(self, filters):
        return daily_cost_report(filters['project'], filters['development'], filters['date_from'], filters['date_to'])


class CustomerWiseReportView(ReportView):
    title = 'Customer-wise Report'
    description = 'For each customer who booked a flat: the booking details, sale value, payments, cost share, installments and what is due.'
    phase = 'All phases'
    pdf_name = 'customer_wise_report'

    def build(self, filters):
        return customer_wise_report(filters['project'], filters['development'])
