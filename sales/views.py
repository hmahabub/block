from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.db.models import Q, Sum
from django.urls import reverse_lazy
from django.utils import timezone
from django.views.generic import CreateView, DetailView, ListView, UpdateView

from core.mixins import CreateAuditMixin, UpdateAuditMixin
from projects.models import Flat, Project

from .forms import CustomerPaymentForm, FlatSaleForm
from .models import CustomerPayment, FlatSale


class FlatSaleListView(LoginRequiredMixin, ListView):
    model = FlatSale
    template_name = 'sales/sale_list.html'
    context_object_name = 'object_list'
    paginate_by = 20

    def get_queryset(self):
        queryset = super().get_queryset().select_related('project', 'flat', 'customer')
        q = self.request.GET.get('q')
        project_id = self.request.GET.get('project')
        status = self.request.GET.get('status')
        if q:
            queryset = queryset.filter(
                Q(sale_no__icontains=q) | Q(customer__name__icontains=q) | Q(flat__flat_no__icontains=q)
            )
        if project_id:
            queryset = queryset.filter(project_id=project_id)
        if status:
            queryset = queryset.filter(status=status)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['projects'] = Project.objects.all()
        context['status_choices'] = FlatSale.Status.choices
        return context


class FlatSaleDetailView(LoginRequiredMixin, DetailView):
    model = FlatSale
    template_name = 'sales/sale_detail.html'
    context_object_name = 'object'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['payments'] = self.object.payments.all()
        return context


class FlatSaleCreateView(PermissionRequiredMixin, CreateAuditMixin, CreateView):
    model = FlatSale
    form_class = FlatSaleForm
    template_name = 'sales/sale_form.html'
    permission_required = 'sales.add_flatsale'

    def get_initial(self):
        initial = super().get_initial()
        initial['sale_date'] = timezone.now().date()
        flat_id = self.request.GET.get('flat')
        if flat_id:
            try:
                flat = Flat.objects.get(pk=flat_id)
                initial['flat'] = flat
                initial['base_price'] = flat.base_price
            except Flat.DoesNotExist:
                pass
        return initial

    def get_success_url(self):
        return reverse_lazy('sales:detail', kwargs={'pk': self.object.pk})


class FlatSaleUpdateView(PermissionRequiredMixin, UpdateAuditMixin, UpdateView):
    model = FlatSale
    form_class = FlatSaleForm
    template_name = 'sales/sale_form.html'
    permission_required = 'sales.change_flatsale'

    def get_success_url(self):
        return reverse_lazy('sales:detail', kwargs={'pk': self.object.pk})


class CustomerPaymentListView(LoginRequiredMixin, ListView):
    model = CustomerPayment
    template_name = 'sales/payment_list.html'
    context_object_name = 'object_list'
    paginate_by = 30

    def get_queryset(self):
        queryset = super().get_queryset().select_related('customer', 'sale', 'sale__flat')
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
                sale = FlatSale.objects.get(pk=sale_id)
                initial['sale'] = sale
                initial['customer'] = sale.customer
            except FlatSale.DoesNotExist:
                pass
        return initial


class FlatSaleInvoiceView(LoginRequiredMixin, DetailView):
    model = FlatSale
    template_name = 'sales/sale_invoice.html'
    context_object_name = 'sale'

    def get_queryset(self):
        return super().get_queryset().select_related('customer', 'flat', 'project')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['payments'] = self.object.payments.order_by('payment_date', 'id')
        return context


class CustomerPaymentReceiptView(LoginRequiredMixin, DetailView):
    model = CustomerPayment
    template_name = 'sales/payment_receipt.html'
    context_object_name = 'payment'

    def get_queryset(self):
        return super().get_queryset().select_related('customer', 'sale', 'sale__flat', 'sale__project')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        payment = self.object
        earlier = payment.sale.payments.filter(
            Q(payment_date__lt=payment.payment_date)
            | Q(payment_date=payment.payment_date, pk__lte=payment.pk)
        )
        # Position as of this payment, not today, so an old receipt stays accurate.
        context['received_to_date'] = earlier.aggregate(total=Sum('amount'))['total'] or 0
        context['balance_after'] = payment.sale.net_sale_value - context['received_to_date']
        return context
