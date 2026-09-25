from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.db.models import Q
from django.urls import reverse_lazy
from django.views.generic import CreateView, DetailView, ListView, UpdateView

from core.mixins import CreateAuditMixin, UpdateAuditMixin

from .forms import CustomerForm
from .models import Customer


class CustomerListView(LoginRequiredMixin, ListView):
    model = Customer
    template_name = 'customers/customer_list.html'
    context_object_name = 'object_list'
    paginate_by = 15

    def get_queryset(self):
        queryset = super().get_queryset()
        q = self.request.GET.get('q')
        if q:
            queryset = queryset.filter(
                Q(name__icontains=q)
                | Q(phone__icontains=q)
                | Q(email__icontains=q)
                | Q(identification_no__icontains=q)
                | Q(father_name__icontains=q)
            )
        return queryset


class CustomerDetailView(LoginRequiredMixin, DetailView):
    model = Customer
    template_name = 'customers/customer_detail.html'
    context_object_name = 'object'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['sales'] = self.object.sales.select_related('flat', 'project').all()
        return context


class CustomerCreateView(PermissionRequiredMixin, CreateAuditMixin, CreateView):
    model = Customer
    form_class = CustomerForm
    template_name = 'customers/customer_form.html'
    permission_required = 'customers.add_customer'

    def get_success_url(self):
        return reverse_lazy('customers:detail', kwargs={'pk': self.object.pk})


class CustomerUpdateView(PermissionRequiredMixin, UpdateAuditMixin, UpdateView):
    model = Customer
    form_class = CustomerForm
    template_name = 'customers/customer_form.html'
    permission_required = 'customers.change_customer'

    def get_success_url(self):
        return reverse_lazy('customers:detail', kwargs={'pk': self.object.pk})
