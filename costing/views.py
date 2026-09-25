import calendar
import datetime

from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.db.models import Sum
from django.http import HttpResponse
from django.urls import reverse_lazy
from django.views import View
from django.views.generic import CreateView, DeleteView, DetailView, ListView, UpdateView

from core.mixins import CreateAuditMixin, DeleteAuditMixin, UpdateAuditMixin
from projects.models import Flat, Project

from .filters import filter_project_costs
from .forms import CostCategoryForm, DirectCostForm, ProjectBudgetForm, SharedCostForm
from .models import CostCategory, ProjectBudget, ProjectCost
from .reports import build_cost_report_pdf


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


class ProjectBudgetListView(LoginRequiredMixin, ListView):
    model = ProjectBudget
    template_name = 'costing/budget_list.html'
    context_object_name = 'object_list'
    paginate_by = 30

    def get_queryset(self):
        queryset = super().get_queryset().select_related('project', 'cost_category')
        project_id = self.request.GET.get('project')
        if project_id:
            queryset = queryset.filter(project_id=project_id)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['projects'] = Project.objects.all()
        return context


class ProjectBudgetCreateView(PermissionRequiredMixin, CreateAuditMixin, CreateView):
    model = ProjectBudget
    form_class = ProjectBudgetForm
    template_name = 'costing/budget_form.html'
    success_url = reverse_lazy('costing:budget-list')
    permission_required = 'costing.add_projectbudget'


class ProjectBudgetUpdateView(PermissionRequiredMixin, UpdateAuditMixin, UpdateView):
    model = ProjectBudget
    form_class = ProjectBudgetForm
    template_name = 'costing/budget_form.html'
    success_url = reverse_lazy('costing:budget-list')
    permission_required = 'costing.change_projectbudget'


class ProjectBudgetDeleteView(PermissionRequiredMixin, DeleteAuditMixin, DeleteView):
    model = ProjectBudget
    template_name = 'costing/budget_confirm_delete.html'
    success_url = reverse_lazy('costing:budget-list')
    permission_required = 'costing.delete_projectbudget'


class ProjectCostListView(LoginRequiredMixin, ListView):
    model = ProjectCost
    template_name = 'costing/cost_list.html'
    context_object_name = 'object_list'
    paginate_by = 30

    def get_queryset(self):
        queryset = super().get_queryset().select_related('project', 'cost_category', 'supplier', 'flat')
        queryset, self.applied = filter_project_costs(queryset, self.request.GET)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        params = self.request.GET
        context['projects'] = Project.objects.all()
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


class ProjectCostDetailView(LoginRequiredMixin, DetailView):
    model = ProjectCost
    template_name = 'costing/cost_detail.html'
    context_object_name = 'object'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['allocations'] = self.object.cost_allocations.select_related('flat')
        return context


class _ProjectCostCreateView(PermissionRequiredMixin, CreateAuditMixin, CreateView):
    model = ProjectCost
    template_name = 'costing/cost_form.html'
    permission_required = 'costing.add_projectcost'
    cost_type = None

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['cost_type'] = self.cost_type
        return context

    def get_success_url(self):
        return reverse_lazy('costing:cost-detail', kwargs={'pk': self.object.pk})


class SharedCostCreateView(_ProjectCostCreateView):
    form_class = SharedCostForm
    cost_type = 'shared'

    def get_initial(self):
        initial = super().get_initial()
        project = Project.objects.filter(pk=self.request.GET.get('project')).first()
        if project:
            initial['project'] = project
        return initial


class DirectCostCreateView(_ProjectCostCreateView):
    form_class = DirectCostForm
    cost_type = 'direct'

    def get_initial(self):
        initial = super().get_initial()
        flat = Flat.objects.filter(pk=self.request.GET.get('flat')).first()
        if flat:
            initial['flat'] = flat
        return initial


class ProjectCostUpdateView(PermissionRequiredMixin, UpdateAuditMixin, UpdateView):
    model = ProjectCost
    template_name = 'costing/cost_form.html'
    permission_required = 'costing.change_projectcost'

    def get_form_class(self):
        # A cost stays the kind it was created as: direct if it has a flat, shared otherwise.
        return DirectCostForm if self.object.flat_id else SharedCostForm

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['cost_type'] = 'direct' if self.object.flat_id else 'shared'
        return context

    def get_success_url(self):
        return reverse_lazy('costing:cost-detail', kwargs={'pk': self.object.pk})


class ProjectCostDeleteView(PermissionRequiredMixin, DeleteAuditMixin, DeleteView):
    model = ProjectCost
    template_name = 'costing/cost_confirm_delete.html'
    success_url = reverse_lazy('costing:cost-list')
    permission_required = 'costing.delete_projectcost'



class ProjectCostVoucherView(LoginRequiredMixin, DetailView):
    model = ProjectCost
    template_name = 'costing/cost_voucher.html'
    context_object_name = 'cost'


class ProjectCostReportPDFView(LoginRequiredMixin, View):
    """PDF of the project cost list, honouring the same filters as the on-screen list."""

    def get(self, request):
        costs, applied = filter_project_costs(ProjectCost.objects.all(), request.GET)
        date_from, date_to = applied['date_from'], applied['date_to']
        stamp = f'{date_from or "start"}_to_{date_to or "end"}' if (date_from or date_to) else 'all'
        response = HttpResponse(content_type='application/pdf')
        response['Content-Disposition'] = f'inline; filename="project_costs_{stamp}.pdf"'
        build_cost_report_pdf(response, costs, applied, request.user)
        return response
