from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.db.models import Q
from django.urls import reverse_lazy
from django.views.generic import CreateView, DetailView, ListView, UpdateView

from core.mixins import CreateAuditMixin, UpdateAuditMixin

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
                Q(name__icontains=q) | Q(supplier_code__icontains=q) | Q(phone__icontains=q)
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
