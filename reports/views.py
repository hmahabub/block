from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.views.generic import TemplateView

from customers.models import Customer
from projects.models import Flat, Project


class ReportIndexView(LoginRequiredMixin, TemplateView):
    template_name = 'reports/index.html'


class ProjectProfitabilityReportView(LoginRequiredMixin, TemplateView):
    template_name = 'reports/project_profitability.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        projects = Project.objects.all()
        rows = []
        totals = {'sales': 0, 'cost': 0, 'profit': 0}
        for project in projects:
            sales = project.total_sales_value
            cost = project.total_cost
            profit = sales - cost
            rows.append({
                'project': project,
                'sales': sales,
                'cost': cost,
                'profit': profit,
                'margin': (profit / sales * 100) if sales else None,
            })
            totals['sales'] += sales
            totals['cost'] += cost
            totals['profit'] += profit
        context['rows'] = rows
        context['totals'] = totals
        return context


class FlatWiseReportView(LoginRequiredMixin, TemplateView):
    template_name = 'reports/flat_wise.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        project_id = self.request.GET.get('project')
        flats = Flat.objects.select_related('project').all()
        if project_id:
            flats = flats.filter(project_id=project_id)
        rows = []
        for flat in flats:
            sale = flat.current_sale
            rows.append({
                'flat': flat,
                'sale_value': sale.net_sale_value if sale else 0,
                'cost': flat.total_cost,
                'received': sale.received_amount if sale else 0,
                'receivable': sale.receivable_amount if sale else 0,
                'profit': flat.profit,
            })
        context['rows'] = rows
        context['projects'] = Project.objects.all()
        context['selected_project'] = Project.objects.filter(pk=project_id).first() if project_id else None
        return context


class DuesReportView(LoginRequiredMixin, TemplateView):
    template_name = 'reports/dues.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['receivables'] = (
            Customer.objects.annotate(receivable=Sum('sales__receivable_amount'))
            .filter(receivable__gt=0)
            .order_by('-receivable')
        )
        return context


class FlatWisePDFView(LoginRequiredMixin, TemplateView):
    def get(self, request, project_pk, *args, **kwargs):
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib.units import cm
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Table, TableStyle
        from reportlab.lib.styles import getSampleStyleSheet

        project = get_object_or_404(Project, pk=project_pk)
        flats = project.flats.all()

        response = HttpResponse(content_type='application/pdf')
        response['Content-Disposition'] = f'inline; filename="{project.project_code}_flat_report.pdf"'

        doc = SimpleDocTemplate(response, pagesize=landscape(A4), topMargin=1.5 * cm, bottomMargin=1.5 * cm)
        styles = getSampleStyleSheet()
        elements = [
            Paragraph(f'Flat-Wise Report — {project.project_name} ({project.project_code})', styles['Title']),
        ]

        table_data = [['Flat', 'Floor', 'Area (sqft)', 'Sale Value', 'Cost', 'Received', 'Receivable', 'Profit']]
        for flat in flats:
            sale = flat.current_sale
            table_data.append([
                flat.flat_no,
                str(flat.floor_no),
                f'{flat.saleable_area:,.2f}',
                f'{sale.net_sale_value:,.2f}' if sale else '-',
                f'{flat.total_cost:,.2f}',
                f'{sale.received_amount:,.2f}' if sale else '-',
                f'{sale.receivable_amount:,.2f}' if sale else '-',
                f'{flat.profit:,.2f}' if flat.profit is not None else '-',
            ])

        table = Table(table_data, repeatRows=1)
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#212529')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTSIZE', (0, 0), (-1, -1), 8),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('ALIGN', (2, 1), (-1, -1), 'RIGHT'),
        ]))
        elements.append(table)
        doc.build(elements)
        return response
