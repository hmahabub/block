import calendar
import datetime

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from decimal import Decimal

from django.db.models import Q, Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views import View
from django.views.generic import CreateView, DeleteView, DetailView, FormView, ListView, TemplateView, UpdateView

from core.mixins import CreateAuditMixin, DeleteAuditMixin, UpdateAuditMixin
from core.utils import int_or_none
from core.workspace import WorkspaceMixin, in_workspace
from projects.models import Flat, Project
from reports.excel import XLSX_CONTENT_TYPE, build_xlsx

from .filters import filter_project_costs
from .forms import CostCategoryForm, CostPaymentForm, DirectCostForm, ProjectBudgetForm, SharedCostForm
from .models import CostCategory, CostPayment, ProjectBudget, ProjectCost
from .reports import build_cost_report_pdf, cost_report_table, describe_filters


class CostCategoryListView(LoginRequiredMixin, ListView):
    model = CostCategory
    template_name = 'costing/category_list.html'
    context_object_name = 'object_list'

    def get_queryset(self):
        return CostCategory.objects.filter(parent_category__isnull=True).prefetch_related('subcategories')


class CostCategoryCreateView(PermissionRequiredMixin, CreateAuditMixin, CreateView):
    model = CostCategory
    form_class = CostCategoryForm
    template_name = 'costing/category_form.html'
    success_url = reverse_lazy('costing:category-list')
    permission_required = 'costing.add_costcategory'


class CostCategoryUpdateView(PermissionRequiredMixin, UpdateAuditMixin, UpdateView):
    model = CostCategory
    form_class = CostCategoryForm
    template_name = 'costing/category_form.html'
    success_url = reverse_lazy('costing:category-list')
    permission_required = 'costing.change_costcategory'


class ProjectBudgetListView(WorkspaceMixin, LoginRequiredMixin, ListView):
    model = ProjectBudget
    workspace_lookup = 'project__development'
    template_name = 'costing/budget_list.html'
    context_object_name = 'object_list'
    paginate_by = 30

    def get_queryset(self):
        queryset = super().get_queryset().select_related('project', 'cost_category')
        project_id = int_or_none(self.request.GET.get('project'))
        if project_id:
            queryset = queryset.filter(project_id=project_id)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['projects'] = in_workspace(Project.objects.all(), self.request, 'development')
        return context


class ProjectBudgetCreateView(WorkspaceMixin, PermissionRequiredMixin, CreateAuditMixin, CreateView):
    model = ProjectBudget
    form_class = ProjectBudgetForm
    template_name = 'costing/budget_form.html'
    success_url = reverse_lazy('costing:budget-list')
    permission_required = 'costing.add_projectbudget'


class ProjectBudgetUpdateView(WorkspaceMixin, PermissionRequiredMixin, UpdateAuditMixin, UpdateView):
    model = ProjectBudget
    workspace_lookup = 'project__development'
    form_class = ProjectBudgetForm
    template_name = 'costing/budget_form.html'
    success_url = reverse_lazy('costing:budget-list')
    permission_required = 'costing.change_projectbudget'


class ProjectBudgetDeleteView(WorkspaceMixin, PermissionRequiredMixin, DeleteAuditMixin, DeleteView):
    model = ProjectBudget
    workspace_lookup = 'project__development'
    template_name = 'costing/budget_confirm_delete.html'
    success_url = reverse_lazy('costing:budget-list')
    permission_required = 'costing.delete_projectbudget'


class ProjectCostListView(WorkspaceMixin, LoginRequiredMixin, ListView):
    model = ProjectCost
    workspace_lookup = 'project__development'
    template_name = 'costing/cost_list.html'
    context_object_name = 'object_list'
    paginate_by = 30

    def get_queryset(self):
        queryset = super().get_queryset().select_related('project', 'cost_category', 'supplier', 'flat', 'account').prefetch_related('payments')
        queryset, self.applied = filter_project_costs(queryset, self.request.GET)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        params = self.request.GET
        context['projects'] = in_workspace(Project.objects.all(), self.request, 'development')
        context['total_amount'] = self.get_queryset().aggregate(total=Sum('amount'))['total'] or 0
        context['month'] = params.get('month', '')
        context['date_from'] = params.get('date_from', '')
        context['date_to'] = params.get('date_to', '')
        today = datetime.date.today()
        this_first = today.replace(day=1)
        last_end = this_first - datetime.timedelta(days=1)
        context['this_month'] = (this_first, this_first.replace(day=calendar.monthrange(today.year, today.month)[1]))
        context['last_month'] = (last_end.replace(day=1), last_end)
        return context


class ProjectCostDetailView(WorkspaceMixin, LoginRequiredMixin, DetailView):
    model = ProjectCost
    workspace_lookup = 'project__development'
    template_name = 'costing/cost_detail.html'
    context_object_name = 'object'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['flat_count'] = self.object.project.flat_count
        return context


class _ProjectCostCreateView(WorkspaceMixin, PermissionRequiredMixin, CreateAuditMixin, CreateView):
    model = ProjectCost
    template_name = 'costing/cost_form.html'
    permission_required = 'costing.add_projectcost'
    cost_type = None

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['cost_type'] = self.cost_type
        context['phase_map'] = context['form'].phase_map()
        return context

    def get_success_url(self):
        return reverse_lazy('costing:cost-detail', kwargs={'pk': self.object.pk})


class SharedCostCreateView(_ProjectCostCreateView):
    form_class = SharedCostForm
    cost_type = 'shared'

    def get_initial(self):
        initial = super().get_initial()
        project = Project.objects.filter(pk=int_or_none(self.request.GET.get('project'))).first()
        if project:
            initial['project'] = project
        return initial


class DirectCostCreateView(_ProjectCostCreateView):
    form_class = DirectCostForm
    cost_type = 'direct'

    def get_initial(self):
        initial = super().get_initial()
        flat = Flat.objects.filter(pk=int_or_none(self.request.GET.get('flat'))).first()
        if flat:
            initial['flat'] = flat
        return initial


class _ConfirmedCostLock:
    """A cost confirmed in the books is part of the book: it can be viewed and printed, never changed or deleted."""

    def dispatch(self, request, *args, **kwargs):
        if request.user.has_perm(self.permission_required):
            cost = ProjectCost.objects.filter(pk=kwargs['pk']).first()
            if cost and cost.is_confirmed:
                messages.error(request, f'{cost.voucher_no} has a payment confirmed in the books and cannot be changed or deleted.')
                return redirect(cost)
        return super().dispatch(request, *args, **kwargs)


class ProjectCostUpdateView(_ConfirmedCostLock, WorkspaceMixin, PermissionRequiredMixin, UpdateAuditMixin, UpdateView):
    model = ProjectCost
    workspace_lookup = 'project__development'
    template_name = 'costing/cost_form.html'
    permission_required = 'costing.change_projectcost'

    def get_form_class(self):
        # A cost stays the kind it was created as: direct if it has a flat, shared otherwise.
        return DirectCostForm if self.object.flat_id else SharedCostForm

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['cost_type'] = 'direct' if self.object.flat_id else 'shared'
        context['phase_map'] = context['form'].phase_map()
        return context

    def get_success_url(self):
        return reverse_lazy('costing:cost-detail', kwargs={'pk': self.object.pk})


class ProjectCostDeleteView(_ConfirmedCostLock, WorkspaceMixin, PermissionRequiredMixin, DeleteAuditMixin, DeleteView):
    model = ProjectCost

    def dispatch(self, request, *args, **kwargs):
        cost = ProjectCost.objects.filter(pk=kwargs['pk']).first()
        if cost and request.user.has_perm(self.permission_required) and cost.payments.exists():
            messages.error(request, f'{cost.voucher_no} has payments under it: remove them first, then the voucher can be deleted.')
            return redirect(cost)
        return super().dispatch(request, *args, **kwargs)

    workspace_lookup = 'project__development'
    template_name = 'costing/cost_confirm_delete.html'
    success_url = reverse_lazy('costing:cost-list')
    permission_required = 'costing.delete_projectcost'



class VoucherPaymentsView(LoginRequiredMixin, TemplateView):
    """Every cost voucher with what is paid and due, and the payments made. A voucher is paid from here: press Pay."""

    template_name = 'costing/voucher_payments.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        params = self.request.GET
        costs = (
            in_workspace(ProjectCost.objects.all(), self.request, 'project__development')
            .select_related('project', 'cost_category', 'supplier').prefetch_related('payments').order_by('-date', '-id')
        )
        q = (params.get('q') or '').strip()
        if q:
            costs = costs.filter(Q(supplier__name__icontains=q) | Q(paid_to__icontains=q) | Q(description__icontains=q) | Q(reference_no__icontains=q)
                                 | Q(cost_category__name__icontains=q) | Q(pk__in=[int(''.join(ch for ch in q if ch.isdigit()))] if q.upper().startswith('CV') and any(ch.isdigit() for ch in q) else []))
        show = params.get('show') if params.get('show') in ('due', 'paid', 'all') else 'due'
        rows = list(costs)
        if show == 'due':
            rows = [c for c in rows if c.due_amount > 0]
        elif show == 'paid':
            rows = [c for c in rows if c.due_amount <= 0]
        payments = (
            in_workspace(CostPayment.objects.all(), self.request, 'cost__project__development')
            .select_related('cost', 'cost__supplier', 'account').order_by('-date', '-id')[:30]
        )
        context.update({
            'rows': rows, 'show': show, 'q': q, 'payments': payments,
            'total_due': sum((c.due_amount for c in rows), Decimal('0')),
            'can_pay': self.request.user.has_perm('costing.add_costpayment'),
        })
        return context


class CostPaymentCreateView(PermissionRequiredMixin, FormView):
    """Pay a cost voucher, wholly or in part. This is where cost payments are made: under the voucher."""

    form_class = CostPaymentForm
    template_name = 'costing/payment_form.html'
    permission_required = 'costing.add_costpayment'

    def dispatch(self, request, *args, **kwargs):
        self.cost = get_object_or_404(in_workspace(ProjectCost.objects.select_related('project', 'cost_category', 'supplier'), request, 'project__development'), pk=kwargs['pk'])
        if request.user.is_authenticated and request.user.has_perm(self.permission_required) and self.cost.due_amount <= 0:
            messages.info(request, f'{self.cost.voucher_no} is already paid in full.')
            return redirect('costing:voucher-payments')
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['cost'] = self.cost
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['cost'] = self.cost
        return context

    def form_valid(self, form):
        payment = form.save()
        messages.success(self.request, f'{payment.payment_no}: {payment.amount:,.2f} paid under {self.cost.voucher_no}.')
        return redirect('costing:voucher-payments')


class CostPaymentDeleteView(PermissionRequiredMixin, View):
    """POST-only: remove a payment that has not been confirmed in the books yet."""

    http_method_names = ['post']
    permission_required = 'costing.delete_costpayment'

    def post(self, request, pk):
        payment = get_object_or_404(in_workspace(CostPayment.objects.select_related('cost'), request, 'cost__project__development'), pk=pk)
        number, cost = payment.payment_no, payment.cost
        if payment.is_confirmed:
            messages.error(request, f'{number} is confirmed in the books and cannot be removed.')
        else:
            payment.delete()
            messages.success(request, f'{number} was removed.')
        return redirect(cost)


class ProjectCostVoucherView(WorkspaceMixin, LoginRequiredMixin, DetailView):
    model = ProjectCost
    workspace_lookup = 'project__development'
    template_name = 'costing/cost_voucher.html'
    context_object_name = 'cost'


class ProjectCostReportExcelView(LoginRequiredMixin, View):
    """Excel file of the project cost list, honouring the same filters as the on-screen list."""

    def get(self, request):
        costs, applied = filter_project_costs(in_workspace(ProjectCost.objects.all(), request, 'project__development'), request.GET)
        stamp = f'{applied["date_from"] or "start"}_to_{applied["date_to"] or "end"}' if (applied['date_from'] or applied['date_to']) else 'all'
        response = HttpResponse(content_type=XLSX_CONTENT_TYPE)
        response['Content-Disposition'] = f'attachment; filename="project_costs_{stamp}.xlsx"'
        build_xlsx(response, 'Cost Report', describe_filters(applied), [cost_report_table(costs)], request.user)
        return response


class ProjectCostReportPDFView(LoginRequiredMixin, View):
    """PDF of the project cost list, honouring the same filters as the on-screen list."""

    def get(self, request):
        costs, applied = filter_project_costs(in_workspace(ProjectCost.objects.all(), request, 'project__development'), request.GET)
        date_from, date_to = applied['date_from'], applied['date_to']
        stamp = f'{date_from or "start"}_to_{date_to or "end"}' if (date_from or date_to) else 'all'
        response = HttpResponse(content_type='application/pdf')
        response['Content-Disposition'] = f'inline; filename="project_costs_{stamp}.pdf"'
        build_cost_report_pdf(response, costs, applied, request.user)
        return response
