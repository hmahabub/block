from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.db import transaction
from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.views.generic import CreateView, DetailView, FormView, ListView, UpdateView

from activity_log.services import log_activity
from core.mixins import CreateAuditMixin, UpdateAuditMixin
from core.utils import int_or_none
from projects.models import Flat, Project
from sms.services import notify_payment

from .forms import (
    CustomerPaymentForm,
    FlatSaleForm,
    HonorariumPaymentForm,
    RefundPaymentForm,
    ReferenceForm,
    SaleCancelForm,
)
from .models import CustomerPayment, FlatSale, Reference


class FlatSaleListView(LoginRequiredMixin, ListView):
    model = FlatSale
    template_name = 'sales/sale_list.html'
    context_object_name = 'object_list'
    paginate_by = 20

    def get_queryset(self):
        queryset = super().get_queryset().select_related('project', 'flat', 'customer', 'ref')
        q = self.request.GET.get('q')
        project_id = int_or_none(self.request.GET.get('project'))
        status = self.request.GET.get('status')
        if q:
            queryset = queryset.filter(
                Q(sale_no__icontains=q) | Q(customer__name__icontains=q) | Q(flat__flat_no__icontains=q)
                | Q(ref__name__icontains=q)
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
        sale = self.object
        context['payments'] = sale.payments.select_related('account')
        context['honorarium_payments'] = sale.honorarium_payments.select_related('account')
        context['refund_payments'] = sale.refund_payments.select_related('account')
        return context


class _SaleFormMixin:
    """Gives the sale form its live preview data (project prices per flat)."""

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['price_map'] = context['form'].price_map()
        return context


class FlatSaleCreateView(PermissionRequiredMixin, _SaleFormMixin, CreateAuditMixin, CreateView):
    model = FlatSale
    form_class = FlatSaleForm
    template_name = 'sales/sale_form.html'
    permission_required = 'sales.add_flatsale'

    def get_initial(self):
        initial = super().get_initial()
        flat = Flat.objects.filter(pk=int_or_none(self.request.GET.get('flat')), status=Flat.Status.AVAILABLE).select_related('project').first()
        if flat:
            initial['flat'] = flat
            initial['sale_value'] = flat.quoted_price
        return initial

    def get_success_url(self):
        return reverse_lazy('sales:detail', kwargs={'pk': self.object.pk})


class FlatSaleUpdateView(PermissionRequiredMixin, _SaleFormMixin, UpdateAuditMixin, UpdateView):
    model = FlatSale
    form_class = FlatSaleForm
    template_name = 'sales/sale_form.html'
    permission_required = 'sales.change_flatsale'

    def dispatch(self, request, *args, **kwargs):
        if request.user.has_perm(self.permission_required):
            sale = get_object_or_404(FlatSale, pk=kwargs['pk'])
            if sale.status == FlatSale.Status.CANCELLED:
                messages.error(request, 'A cancelled sale can no longer be edited.')
                return redirect(sale)
        return super().dispatch(request, *args, **kwargs)

    def get_success_url(self):
        return reverse_lazy('sales:detail', kwargs={'pk': self.object.pk})


class FlatSaleCancelView(PermissionRequiredMixin, FormView):
    """Cancel a booking and set what percentage of the customer's money is refundable."""

    form_class = SaleCancelForm
    template_name = 'sales/sale_cancel.html'
    permission_required = 'sales.change_flatsale'

    def dispatch(self, request, *args, **kwargs):
        self.sale = get_object_or_404(FlatSale.objects.select_related('flat', 'customer'), pk=kwargs['pk'])
        if self.sale.status == FlatSale.Status.CANCELLED and request.user.has_perm(self.permission_required):
            messages.error(request, 'This sale is already cancelled.')
            return redirect(self.sale)
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['sale'] = self.sale
        return context

    @transaction.atomic
    def form_valid(self, form):
        sale = self.sale
        sale.cancelled_on = form.cleaned_data['cancelled_on']
        sale.cancel(form.cleaned_data['refund_percent'])
        sale.save()
        log_activity(self.request.user, 'updated', sale)
        messages.success(
            self.request,
            f'{sale.sale_no} cancelled. Refundable to the customer: {sale.refund_amount:,.2f} '
            f'({sale.refund_percent}% of {sale.received_amount:,.2f}).',
        )
        return redirect(sale)


class CustomerPaymentListView(LoginRequiredMixin, ListView):
    model = CustomerPayment
    template_name = 'sales/payment_list.html'
    context_object_name = 'object_list'
    paginate_by = 30

    def get_queryset(self):
        queryset = super().get_queryset().select_related('customer', 'sale', 'sale__flat', 'account')
        customer_id = int_or_none(self.request.GET.get('customer'))
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
        sale = FlatSale.objects.filter(pk=int_or_none(self.request.GET.get('sale'))).exclude(status=FlatSale.Status.CANCELLED).first()
        if sale:
            initial['sale'] = sale
            initial['amount'] = sale.receivable_amount or None
        return initial

    def form_valid(self, form):
        response = super().form_valid(form)
        log = notify_payment(self.object, self.request.user)
        if log is None:
            messages.info(self.request, 'No SMS sent: this customer is excluded from SMS.')
        elif log.status == 'FAILED':
            messages.warning(self.request, f'Payment saved, but the SMS could not be sent: {log.error}')
        return response


class _SalePayoutCreateView(PermissionRequiredMixin, CreateAuditMixin, CreateView):
    """Base for the honorarium and refund payment screens, both opened from a sale."""

    template_name = 'sales/payout_form.html'
    title = ''
    blocked_message = ''

    def dispatch(self, request, *args, **kwargs):
        self.sale = get_object_or_404(FlatSale.objects.select_related('flat', 'customer', 'ref'), pk=kwargs['pk'])
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['sale'] = self.sale
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(sale=self.sale, title=self.title, due=context['form'].due())
        return context

    def get_success_url(self):
        return reverse('sales:detail', kwargs={'pk': self.sale.pk})


class HonorariumPaymentCreateView(_SalePayoutCreateView):
    form_class = HonorariumPaymentForm
    permission_required = 'sales.add_honorariumpayment'
    title = 'Pay honorarium'


class RefundPaymentCreateView(_SalePayoutCreateView):
    form_class = RefundPaymentForm
    permission_required = 'sales.add_refundpayment'
    title = 'Refund to customer'


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
        return super().get_queryset().select_related('customer', 'sale', 'sale__flat', 'sale__project', 'account')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        payment = self.object
        earlier = payment.sale.payments.filter(
            Q(payment_date__lt=payment.payment_date)
            | Q(payment_date=payment.payment_date, pk__lte=payment.pk)
        )
        # Position as of this payment, not today, so an old receipt stays accurate.
        received = earlier.aggregate(total=Sum('amount'))['total'] or 0
        net = payment.sale.net_value
        context['received_to_date'] = received
        context['balance_after'] = max(net - received, 0)
        context['credit_after'] = max(received - net, 0)
        return context


class ReferenceListView(LoginRequiredMixin, ListView):
    model = Reference
    template_name = 'sales/reference_list.html'
    context_object_name = 'object_list'
    paginate_by = 30

    def get_queryset(self):
        queryset = super().get_queryset()
        q = self.request.GET.get('q')
        if q:
            queryset = queryset.filter(Q(name__icontains=q) | Q(phone__icontains=q))
        return queryset


class ReferenceDetailView(LoginRequiredMixin, DetailView):
    model = Reference
    template_name = 'sales/reference_detail.html'
    context_object_name = 'object'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        sales = self.object.sales.exclude(status=FlatSale.Status.CANCELLED).select_related('flat', 'project', 'customer')
        context['sales'] = sales
        context['honorarium_total'] = sum((s.honorarium for s in sales), 0)
        context['honorarium_paid'] = sum((s.honorarium_paid for s in sales), 0)
        return context


class ReferenceCreateView(PermissionRequiredMixin, CreateAuditMixin, CreateView):
    model = Reference
    form_class = ReferenceForm
    template_name = 'sales/reference_form.html'
    permission_required = 'sales.add_reference'

    def get_success_url(self):
        return reverse('sales:reference-detail', kwargs={'pk': self.object.pk})


class ReferenceUpdateView(PermissionRequiredMixin, UpdateAuditMixin, UpdateView):
    model = Reference
    form_class = ReferenceForm
    template_name = 'sales/reference_form.html'
    permission_required = 'sales.change_reference'

    def get_success_url(self):
        return reverse('sales:reference-detail', kwargs={'pk': self.object.pk})
