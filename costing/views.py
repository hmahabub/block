from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.db.models import Q, Sum
from django.urls import reverse_lazy
from django.views.generic import CreateView, DeleteView, DetailView, ListView, UpdateView

from core.mixins import CreateAuditMixin, DeleteAuditMixin, UpdateAuditMixin
from projects.models import Flat, Project

from .forms import CostCategoryForm, DirectCostForm, ProjectBudgetForm, SharedCostForm
from .models import CostCategory, ProjectBudget, ProjectCost


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
        project_id = self.request.GET.get('project')
        status = self.request.GET.get('status')
        cost_type = self.request.GET.get('type')
        q = self.request.GET.get('q')
        if project_id:
            queryset = queryset.filter(project_id=project_id)
        if status:
            queryset = queryset.filter(status=status)
        if cost_type == 'shared':
            queryset = queryset.filter(flat__isnull=True)
        elif cost_type == 'direct':
            queryset = queryset.filter(flat__isnull=False)
        if q:
            queryset = queryset.filter(
                Q(description__icontains=q) | Q(reference_no__icontains=q) | Q(supplier__name__icontains=q)
            )
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['projects'] = Project.objects.all()
        context['status_choices'] = ProjectCost.Status.choices
        totals = self.get_queryset().aggregate(
            total_amount=Sum('amount'), total_paid=Sum('paid_amount'), total_payable=Sum('payable_amount'),
        )
        context.update(totals)
        return context


class ProjectCostDetailView(LoginRequiredMixin, DetailView):
    model = ProjectCost
    template_name = 'costing/cost_detail.html'
    context_object_name = 'object'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['payments'] = self.object.payments.select_related('supplier')
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
