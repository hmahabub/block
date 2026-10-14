import datetime

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponse
from django.views.generic import TemplateView

from core.utils import int_or_none
from projects.models import Project

from . import builders
from .excel import XLSX_CONTENT_TYPE, build_xlsx
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
        project = Project.objects.filter(pk=project_id).first() if project_id else None
        return {'project': project, 'date_from': _date(params.get('date_from')), 'date_to': _date(params.get('date_to'))}

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
            'uses_period': self.uses_period, 'projects': Project.objects.all(),
            'selected_project': filters['project'], 'date_from': filters['date_from'], 'date_to': filters['date_to'],
        })
        return context


class FinanceReportView(ReportView):
    title = 'Finance Report'
    description = 'Sales, cost, receivable and payable across every phase, plus the money in hand.'
    phase = 'All phases'
    pdf_name = 'finance_report'

    def build(self, filters):
        return builders.finance_report(filters['project'])


class PeriodicCollectionReportView(ReportView):
    title = 'Periodic Payment Collection'
    description = 'Customer payments collected, grouped by month, customer and account.'
    phase = 'Pre-development'
    uses_period = True
    pdf_name = 'periodic_collection'

    def build(self, filters):
        return builders.periodic_collection_report(filters['project'], filters['date_from'], filters['date_to'])


class ProfitLossReportView(ReportView):
    title = 'Profit, Loss, Collection and Due'
    description = 'What share sales earn against land, marketing and pre-development cost; what is collected and what is still due.'
    phase = 'Pre-development'
    pdf_name = 'profit_loss_collection_due'

    def build(self, filters):
        return builders.profit_loss_report(filters['project'])


class CustomerPostReportView(ReportView):
    title = 'Customer Balance, Cost, Receivable and Payable'
    description = 'Per customer: balance held, receivable, share of post-development cost and what is payable.'
    phase = 'Post-development'
    pdf_name = 'customer_balance_cost'

    def build(self, filters):
        return builders.customer_post_report(filters['project'])


class FlatWiseReportView(ReportView):
    title = 'Flat-Wise Report'
    description = 'Sale, collection and cost share for each flat.'
    phase = 'All phases'
    pdf_name = 'flat_wise_report'

    def build(self, filters):
        return builders.flat_wise_report(filters['project'])


class DuesReportView(ReportView):
    title = 'Receivables'
    description = 'Outstanding balances still to be collected from customers.'
    phase = 'All phases'
    pdf_name = 'receivables'

    def build(self, filters):
        return builders.dues_report(filters['project'])
