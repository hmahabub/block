from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.db.models import Q
from django.urls import reverse_lazy
from django.utils import timezone
from django.views.generic import CreateView, DetailView, ListView, UpdateView

from core.mixins import CreateAuditMixin, UpdateAuditMixin
from projects.models import Apartment, Project

from .forms import ApartmentSaleForm, CustomerPaymentForm
from .models import ApartmentSale, CustomerPayment


class ApartmentSaleListView(LoginRequiredMixin, ListView):
    model = ApartmentSale
    template_name = 'sales/sale_list.html'
    context_object_name = 'object_list'
    paginate_by = 20

    def get_queryset(self):
        queryset = super().get_queryset().select_related('project', 'apartment', 'customer')
        q = self.request.GET.get('q')
        project_id = self.request.GET.get('project')
        status = self.request.GET.get('status')
        if q:
            queryset = queryset.filter(
                Q(sale_no__icontains=q) | Q(customer__name__icontains=q) | Q(apartment__apartment_no__icontains=q)
            )
        if project_id:
            queryset = queryset.filter(project_id=project_id)
        if status:
            queryset = queryset.filter(status=status)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['projects'] = Project.objects.all()
        context['status_choices'] = ApartmentSale.Status.choices
        return context


class ApartmentSaleDetailView(LoginRequiredMixin, DetailView):
    model = ApartmentSale
    template_name = 'sales/sale_detail.html'
    context_object_name = 'object'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['payments'] = self.object.payments.all()
        return context


class ApartmentSaleCreateView(PermissionRequiredMixin, CreateAuditMixin, CreateView):
    model = ApartmentSale
    form_class = ApartmentSaleForm
    template_name = 'sales/sale_form.html'
    permission_required = 'sales.add_apartmentsale'

    def get_initial(self):
        initial = super().get_initial()
        initial['sale_date'] = timezone.now().date()
        apartment_id = self.request.GET.get('apartment')
        if apartment_id:
            try:
                apartment = Apartment.objects.get(pk=apartment_id)
                initial['apartment'] = apartment
                initial['base_price'] = apartment.base_price
            except Apartment.DoesNotExist:
                pass
        return initial

    def get_success_url(self):
        return reverse_lazy('sales:detail', kwargs={'pk': self.object.pk})


class ApartmentSaleUpdateView(PermissionRequiredMixin, UpdateAuditMixin, UpdateView):
    model = ApartmentSale
    form_class = ApartmentSaleForm
    template_name = 'sales/sale_form.html'
    permission_required = 'sales.change_apartmentsale'

    def get_success_url(self):
        return reverse_lazy('sales:detail', kwargs={'pk': self.object.pk})


class CustomerPaymentListView(LoginRequiredMixin, ListView):
    model = CustomerPayment
    template_name = 'sales/payment_list.html'
    context_object_name = 'object_list'
    paginate_by = 30

    def get_queryset(self):
        queryset = super().get_queryset().select_related('customer', 'sale', 'sale__apartment')
        customer_id = self.request.GET.get('customer')
        if customer_id:
            queryset = queryset.filter(customer_id=customer_id)
        return queryset


class CustomerPaymentCreateView(PermissionRequiredMixin, CreateAuditMixin, CreateView):
    model = CustomerPayment
    form_class = CustomerPaymentForm
    template_name = 'sales/payment_form.html'
    success_url = reverse_lazy('sales:payment-list')
    permission_required = 'sales.add_customerpayment'

    def get_initial(self):
        initial = super().get_initial()
        initial['payment_date'] = timezone.now().date()
        sale_id = self.request.GET.get('sale')
        if sale_id:
            try:
                sale = ApartmentSale.objects.get(pk=sale_id)
                initial['sale'] = sale
                initial['customer'] = sale.customer
            except ApartmentSale.DoesNotExist:
                pass
        return initial
