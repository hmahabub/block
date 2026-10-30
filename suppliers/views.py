import datetime
from decimal import Decimal

from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.db.models import Q
from django.http import HttpResponse
from django.urls import reverse_lazy
from django.views.generic import CreateView, DetailView, ListView, UpdateView

from core.formatting import DATE, MONEY
from core.mixins import CreateAuditMixin, UpdateAuditMixin
from core.reauth import money_visible
from core.utils import int_or_none
from reports.excel import XLSX_CONTENT_TYPE, build_xlsx
from reports.tables import Column, ReportTable

from .forms import SupplierForm
from .models import Supplier


class SupplierListView(LoginRequiredMixin, ListView):
    model = Supplier
    template_name = 'suppliers/supplier_list.html'
    context_object_name = 'object_list'
    paginate_by = 15

    def get_queryset(self):
        queryset = super().get_queryset()
        q = self.request.GET.get('q')
        if q:
            queryset = queryset.filter(
                Q(name__icontains=q) | Q(supplier_code__icontains=q) | Q(phone__icontains=q) | Q(tin__icontains=q)
            )
        return queryset


class SupplierDetailView(LoginRequiredMixin, DetailView):
    model = Supplier
    template_name = 'suppliers/supplier_detail.html'
    context_object_name = 'object'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['project_costs'] = self.object.project_costs.select_related('project', 'cost_category').all()
        return context


def _date(value):
    try:
        return datetime.date.fromisoformat(value) if value else None
    except ValueError:
        return None


class SupplierLedgerView(LoginRequiredMixin, DetailView):
    """Every payment made to one supplier, oldest first, with a running total.

    Cost entries count as paid when they are recorded, so the ledger is the list of payments. The running total is
    what the company has paid this supplier up to and including each line. ?format=xlsx downloads it as Excel.
    """

    model = Supplier
    template_name = 'suppliers/supplier_ledger.html'
    context_object_name = 'object'

    def ledger(self):
        from costing.models import ProjectCost
        from projects.models import Project

        params = self.request.GET
        building = Project.objects.filter(pk=int_or_none(params.get('project'))).first()
        phase = params.get('phase') if params.get('phase') in ('PRE', 'POST') else ''
        date_from, date_to = _date(params.get('date_from')), _date(params.get('date_to'))

        costs = ProjectCost.objects.filter(supplier=self.object).select_related(
            'project', 'cost_category', 'cost_category__parent_category', 'flat', 'account',
        ).order_by('date', 'id')
        def matches(cost):
            return (not building or cost.project_id == building.pk) and (not phase or cost.phase == phase)

        everything = [c for c in costs if matches(c)]
        # What was paid before the period starts is carried forward, so the running total is right for any period.
        before = sum((c.amount for c in everything if date_from and c.date < date_from), Decimal('0'))
        rows = [c for c in everything if (not date_from or c.date >= date_from) and (not date_to or c.date <= date_to)]
        running = before
        for cost in rows:
            running += cost.amount
            cost.running_total = running
        by_building = {}
        for cost in rows:
            by_building[cost.project] = by_building.get(cost.project, Decimal('0')) + cost.amount
        return {
            'rows': rows, 'brought_forward': before, 'period_total': sum((c.amount for c in rows), Decimal('0')),
            'closing_total': running, 'by_building': sorted(by_building.items(), key=lambda item: item[0].project_name),
            'building': building, 'phase': phase, 'date_from': date_from, 'date_to': date_to,
            'buildings': Project.objects.filter(costs__supplier=self.object).distinct(),
        }

    def get(self, request, *args, **kwargs):
        self.object = self.get_object()
        if not money_visible(request):
            return self.render_to_response(self.get_context_data(object=self.object, locked=True))
        if request.GET.get('format') == 'xlsx':
            return self.excel()
        return self.render_to_response(self.get_context_data(object=self.object, **self.ledger()))

    def excel(self):
        supplier, data = self.object, self.ledger()
        rows = [[data['date_from'], '', '', 'Brought forward', '', '', None, data['brought_forward']]] if data['date_from'] else []
        rows += [
            [c.date, c.voucher_no, c.project.project_name, f'{c.cost_category} - {c.description}'.rstrip(' -'),
             c.get_phase_display(), c.account.name if c.account else None, c.amount, c.running_total]
            for c in data['rows']
        ]
        table = ReportTable(
            'Payments', [Column('Date', DATE), Column('Voucher'), Column('Building'), Column('Particulars'), Column('Phase'),
                         Column('Paid from'), Column('Paid', MONEY), Column('Total paid', MONEY)],
            rows, ['Total', '', '', '', '', '', data['period_total'], data['closing_total']],
        )
        lines = [f'Supplier: {supplier.name} ({supplier.supplier_code})']
        if supplier.tin:
            lines.append(f'TIN: {supplier.tin}')
        response = HttpResponse(content_type=XLSX_CONTENT_TYPE)
        response['Content-Disposition'] = f'attachment; filename="supplier_ledger_{supplier.supplier_code}.xlsx"'
        build_xlsx(response, 'Supplier ledger', lines, [table], self.request.user)
        return response


class SupplierCreateView(PermissionRequiredMixin, CreateAuditMixin, CreateView):
    model = Supplier
    form_class = SupplierForm
    template_name = 'suppliers/supplier_form.html'
    permission_required = 'suppliers.add_supplier'

    def get_success_url(self):
        return reverse_lazy('suppliers:detail', kwargs={'pk': self.object.pk})


class SupplierUpdateView(PermissionRequiredMixin, UpdateAuditMixin, UpdateView):
    model = Supplier
    form_class = SupplierForm
    template_name = 'suppliers/supplier_form.html'
    permission_required = 'suppliers.change_supplier'

    def get_success_url(self):
        return reverse_lazy('suppliers:detail', kwargs={'pk': self.object.pk})
