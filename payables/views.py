from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.urls import reverse_lazy
from django.views.generic import CreateView, ListView

from core.mixins import CreateAuditMixin
from costing.models import ProjectCost

from .forms import SupplierPaymentForm
from .models import SupplierPayment


class SupplierPaymentListView(LoginRequiredMixin, ListView):
    model = SupplierPayment
    template_name = 'payables/payment_list.html'
    context_object_name = 'object_list'
    paginate_by = 30

    def get_queryset(self):
        queryset = super().get_queryset().select_related('supplier', 'project_cost', 'project_cost__project')
        supplier_id = self.request.GET.get('supplier')
        if supplier_id:
            queryset = queryset.filter(supplier_id=supplier_id)
        return queryset


class SupplierPaymentCreateView(PermissionRequiredMixin, CreateAuditMixin, CreateView):
    model = SupplierPayment
    form_class = SupplierPaymentForm
    template_name = 'payables/payment_form.html'
    success_url = reverse_lazy('payables:list')
    permission_required = 'payables.add_supplierpayment'

    def get_initial(self):
        initial = super().get_initial()
        cost_id = self.request.GET.get('project_cost')
        if cost_id:
            try:
                cost = ProjectCost.objects.get(pk=cost_id)
                initial['project_cost'] = cost
                initial['supplier'] = cost.supplier
            except ProjectCost.DoesNotExist:
                pass
        return initial
