import datetime
from decimal import Decimal

from django.contrib import messages
from django.http import Http404
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.db import transaction
from django.db.models import DecimalField, ExpressionWrapper, F, Prefetch, Q, Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views import View
from django.views.generic import CreateView, DetailView, FormView, ListView, TemplateView, UpdateView

from core.mixins import CreateAuditMixin, UpdateAuditMixin
from core.formatting import DATE, MONEY
from core.reauth import money_visible
from core.utils import int_or_none
from core.workspace import WorkspaceMixin, current_development, in_workspace
from projects.models import Flat, Project
from reports.excel import XLSX_CONTENT_TYPE, build_xlsx
from reports.tables import Column, ReportTable
from sms.feedback import report_sms
from sms.services import notify_booking, notify_payment
from sms.whatsapp import sale_pk_from_token

from .forms import (
    CustomerPaymentForm,
    FlatSaleForm,
    HonorariumPaymentForm,
    RefundPaymentForm,
    ReferenceForm,
    SaleCancelForm,
)
from .invoice_pdf import build_invoice_document_pdf, build_invoice_pdf
from .models import CustomerPayment, FlatSale, HonorariumPayment, Invoice, Reference


class FlatSaleListView(WorkspaceMixin, LoginRequiredMixin, ListView):
    model = FlatSale
    workspace_lookup = 'project__development'
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
        context['projects'] = in_workspace(Project.objects.all(), self.request, 'development')
        context['status_choices'] = FlatSale.Status.choices
        return context


class FlatSaleDetailView(WorkspaceMixin, LoginRequiredMixin, DetailView):
    model = FlatSale
    workspace_lookup = 'project__development'
    template_name = 'sales/sale_detail.html'
    context_object_name = 'object'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        sale = self.object
        context['payments'] = sale.payments.select_related('account', 'invoice', 'invoice__charge__installment')
        context['invoices'] = sale.invoices.select_related('charge__installment').prefetch_related('payments')
        context['honorarium_payments'] = sale.honorarium_payments.select_related('account')
        context['refund_payments'] = sale.refund_payments.select_related('account')
        from installments.services import allocate, due_total, overdue_total

        rows = allocate(sale) if sale.status != FlatSale.Status.CANCELLED else []
        context.update(installment_rows=rows, installment_due=due_total(rows), installment_overdue=overdue_total(rows))
        return context


class _SaleFormMixin:
    """Gives the sale form its live preview data (project prices per flat)."""

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['price_map'] = context['form'].price_map(include_base=money_visible(self.request))
        return context


class FlatSaleCreateView(WorkspaceMixin, PermissionRequiredMixin, _SaleFormMixin, CreateAuditMixin, CreateView):
    model = FlatSale
    form_class = FlatSaleForm
    template_name = 'sales/sale_form.html'
    permission_required = 'sales.add_flatsale'

    def get_initial(self):
        initial = super().get_initial()
        flat = Flat.objects.filter(pk=int_or_none(self.request.GET.get('flat')), status=Flat.Status.AVAILABLE).select_related('project').first()
        if flat:
            initial['flat'] = flat
            initial['flat_sale_value'] = flat.quoted_price
        return initial

    def form_valid(self, form):
        response = super().form_valid(form)
        report_sms(self.request, notify_booking(self.object, self.request.user), 'Booking')
        return response

    def get_success_url(self):
        return reverse_lazy('sales:detail', kwargs={'pk': self.object.pk})


class FlatSaleUpdateView(WorkspaceMixin, PermissionRequiredMixin, _SaleFormMixin, UpdateAuditMixin, UpdateView):
    model = FlatSale
    workspace_lookup = 'project__development'
    form_class = FlatSaleForm
    template_name = 'sales/sale_form.html'
    permission_required = 'sales.change_flatsale'

    def dispatch(self, request, *args, **kwargs):
        if request.user.has_perm(self.permission_required):
            sale = get_object_or_404(in_workspace(FlatSale.objects.all(), request, 'project__development'), pk=kwargs['pk'])
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
        sales = in_workspace(FlatSale.objects.select_related('flat', 'customer'), request, 'project__development')
        self.sale = get_object_or_404(sales, pk=kwargs['pk'])
        if self.sale.status == FlatSale.Status.CANCELLED and request.user.has_perm(self.permission_required):
            messages.error(request, 'This sale is already cancelled.')
            return redirect(self.sale)
        if self.sale.status == FlatSale.Status.REGISTERED and request.user.has_perm(self.permission_required):
            messages.error(request, 'The registry of this flat is completed. Undo the registry first if the sale really has to be cancelled.')
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
        messages.success(
            self.request,
            f'{sale.sale_no} cancelled. Refundable to the customer: {sale.refund_amount:,.2f} '
            f'({sale.refund_percent}% of {sale.received_amount:,.2f}).',
        )
        return redirect(sale)


class FlatSaleRegistryView(PermissionRequiredMixin, View):
    """POST-only: mark the registry of a sale completed (the flat becomes Registered), or undo that."""

    http_method_names = ['post']
    permission_required = 'sales.change_flatsale'

    def post(self, request, pk):
        sale = get_object_or_404(in_workspace(FlatSale.objects.all(), request, 'project__development'), pk=pk)
        if sale.status == FlatSale.Status.CANCELLED:
            messages.error(request, 'A cancelled sale has no registry.')
            return redirect(sale)
        if request.POST.get('action') == 'undo':
            sale.undo_registry()
            sale.save()
            messages.success(request, f'Registry undone: {sale.flat} is Booked again.')
            return redirect(sale)
        try:
            day = datetime.date.fromisoformat(request.POST.get('registered_on') or '')
        except ValueError:
            day = timezone.localdate()
        sale.register(day)
        sale.save()
        messages.success(request, f'Registry completed on {day:%d %b %Y}: {sale.flat} is now Registered.')
        return redirect(sale)


class CustomerPaymentListView(WorkspaceMixin, LoginRequiredMixin, ListView):
    model = CustomerPayment
    workspace_lookup = 'sale__project__development'
    template_name = 'sales/payment_list.html'
    context_object_name = 'object_list'
    paginate_by = 30

    def get_queryset(self):
        queryset = super().get_queryset().select_related('customer', 'sale', 'sale__flat', 'account')
        customer_id = int_or_none(self.request.GET.get('customer'))
        if customer_id:
            queryset = queryset.filter(customer_id=customer_id)
        return queryset


class CustomerPaymentCreateView(WorkspaceMixin, PermissionRequiredMixin, CreateAuditMixin, CreateView):
    model = CustomerPayment
    form_class = CustomerPaymentForm
    template_name = 'sales/payment_form.html'
    permission_required = 'sales.add_customerpayment'

    def dispatch(self, request, *args, **kwargs):
        """A payment is recorded from an invoice: with none named, go and choose one."""
        invoices = Invoice.objects.exclude(sale__status=FlatSale.Status.CANCELLED).select_related('sale', 'sale__customer', 'sale__flat', 'sale__project')
        invoices = invoices.filter(sale__project__development=current_development(request))
        self.invoice = invoices.filter(pk=int_or_none(request.GET.get('invoice') or request.POST.get('invoice'))).first()
        if self.invoice is None and request.user.is_authenticated and request.user.has_perm(self.permission_required):
            messages.info(request, 'Payments are recorded from an invoice: choose the invoice and press Pay.')
            return redirect('sales:invoice-list')
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['development'] = current_development(self.request)
        kwargs['invoice'] = self.invoice
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['invoice'] = self.invoice
        return context

    def get_success_url(self):
        return self.invoice.get_absolute_url()

    def form_valid(self, form):
        response = super().form_valid(form)
        report_sms(self.request, notify_payment(self.object, self.request.user), 'Payment')
        return response


class _SalePayoutCreateView(PermissionRequiredMixin, CreateAuditMixin, CreateView):
    """Base for the honorarium and refund payment screens, both opened from a sale."""

    template_name = 'sales/payout_form.html'
    title = ''
    blocked_message = ''

    def dispatch(self, request, *args, **kwargs):
        sales = in_workspace(FlatSale.objects.select_related('flat', 'customer', 'ref'), request, 'project__development')
        self.sale = get_object_or_404(sales, pk=kwargs['pk'])
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
    """Pay the honorarium voucher of a booking. Opened from Costing > Honorarium, which is where it is paid."""

    form_class = HonorariumPaymentForm
    permission_required = 'sales.add_honorariumpayment'
    title = 'Pay honorarium'

    def get_success_url(self):
        return reverse('costing:honorarium-list')



class RefundPaymentCreateView(_SalePayoutCreateView):
    form_class = RefundPaymentForm
    permission_required = 'sales.add_refundpayment'
    title = 'Refund to customer'


class InvoiceListView(LoginRequiredMixin, TemplateView):
    """Every invoice of the project: one for each flat booking and one for each installment, with what is paid and due."""

    template_name = 'sales/invoice_list.html'
    paginate_by = 40

    def get_context_data(self, **kwargs):
        from django.core.paginator import Paginator

        context = super().get_context_data(**kwargs)
        params = self.request.GET
        invoices = (
            Invoice.objects.filter(sale__project__development=current_development(self.request))
            .exclude(sale__status=FlatSale.Status.CANCELLED)
            .select_related('sale', 'sale__customer', 'sale__flat', 'sale__project', 'charge', 'charge__installment')
            .prefetch_related('payments', 'sale__installment_charges')
            .order_by('-issued_on', '-id')
        )
        q = (params.get('q') or '').strip()
        if q:
            number = ''.join(ch for ch in q if ch.isdigit())
            invoices = invoices.filter(
                Q(sale__sale_no__icontains=q) | Q(sale__customer__name__icontains=q) | Q(sale__flat__flat_no__icontains=q)
                | Q(sale__customer__customer_code__icontains=q) | (Q(pk=int(number)) if number and q.upper().startswith('INV') else Q(pk__in=[]))
            )
        kind = params.get('kind') if params.get('kind') in Invoice.Kind.values else ''
        if kind:
            invoices = invoices.filter(kind=kind)
        rows = [{'invoice': i, 'total': i.total, 'paid': i.paid, 'due': i.due, 'status': i.status} for i in invoices]
        show = params.get('show') if params.get('show') in ('open', 'overdue', 'paid') else ''
        if show == 'open':
            rows = [r for r in rows if r['due'] > 0]
        elif show == 'overdue':
            rows = [r for r in rows if r['status'] == 'Overdue']
        elif show == 'paid':
            rows = [r for r in rows if r['status'] == 'Paid']
        page = Paginator(rows, self.paginate_by).get_page(params.get('page'))
        context.update({
            'page_obj': page, 'rows': page.object_list, 'is_paginated': page.has_other_pages(), 'q': q, 'kind': kind, 'show': show,
            'kinds': Invoice.Kind.choices, 'total_due': sum((r['due'] for r in rows), Decimal('0')),
            'count': len(rows),
        })
        return context


class InvoiceDetailView(WorkspaceMixin, LoginRequiredMixin, DetailView):
    """One invoice, printable: what it is for, the amount, and the payments received under it. ?format=pdf for the PDF."""

    model = Invoice
    template_name = 'sales/invoice_document.html'
    context_object_name = 'invoice'
    workspace_lookup = 'sale__project__development'

    def get_queryset(self):
        return super().get_queryset().select_related('sale', 'sale__customer', 'sale__flat', 'sale__project', 'charge', 'charge__installment')

    def get(self, request, *args, **kwargs):
        self.object = self.get_object()
        if request.GET.get('format') != 'pdf':
            return self.render_to_response(self.get_context_data(object=self.object))
        invoice = self.object
        response = HttpResponse(content_type='application/pdf')
        response['Content-Disposition'] = f'inline; filename="{invoice.number}.pdf"'
        build_invoice_document_pdf(response, invoice, invoice.payments.select_related('account').order_by('payment_date', 'id'))
        return response

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['sale'] = self.object.sale
        context['payments'] = self.object.payments.select_related('account').order_by('payment_date', 'id')
        return context


def _date(value):
    try:
        return datetime.date.fromisoformat(value) if value else None
    except ValueError:
        return None


class HonorariumListView(LoginRequiredMixin, TemplateView):
    """Every sale that carries an honorarium, with the payments made against it, for the project being worked in.

    Filter by reference, by payment date, or to what is still due. ?format=xlsx downloads it as Excel."""

    template_name = 'sales/honorarium_list.html'

    def data(self):
        params = self.request.GET
        reference = Reference.objects.filter(pk=int_or_none(params.get('ref'))).first()
        date_from, date_to = _date(params.get('date_from')), _date(params.get('date_to'))
        only_due = params.get('only_due') == '1'

        extra = ExpressionWrapper(F('sale_value') - F('base_price') - F('parking_price'), output_field=DecimalField())
        sales = (
            in_workspace(FlatSale.objects.annotate(extra=extra), self.request, 'project__development')
            .filter(Q(extra__gt=0) | Q(honorarium_payments__isnull=False)).distinct()
            .select_related('flat', 'customer', 'ref', 'project')
            .prefetch_related(Prefetch(
                'honorarium_payments', queryset=HonorariumPayment.objects.select_related('account').order_by('date', 'id'),
                to_attr='listed_payments',
            ))
            .order_by('ref__name', 'sale_no')
        )
        if reference:
            sales = sales.filter(ref=reference)

        rows = []
        for sale in sales:
            payments = [p for p in sale.listed_payments if (not date_from or p.date >= date_from) and (not date_to or p.date <= date_to)]
            paid_ever = sum((p.amount for p in sale.listed_payments), Decimal('0'))
            due = max(sale.honorarium - paid_ever, Decimal('0')) if sale.status != FlatSale.Status.CANCELLED else Decimal('0')
            if (date_from or date_to) and not payments:
                continue
            if only_due and due <= 0:
                continue
            rows.append({
                'sale': sale, 'payments': payments, 'honorarium': sale.honorarium,
                'paid': sum((p.amount for p in payments), Decimal('0')), 'due': due,
            })
        return {
            'rows': rows, 'reference': reference, 'date_from': date_from, 'date_to': date_to, 'only_due': only_due,
            'total_honorarium': sum((r['honorarium'] for r in rows), Decimal('0')),
            'total_paid': sum((r['paid'] for r in rows), Decimal('0')),
            'total_due': sum((r['due'] for r in rows), Decimal('0')),
            'payment_count': sum(len(r['payments']) for r in rows),
        }

    def get(self, request, *args, **kwargs):
        if not money_visible(request):
            return self.render_to_response(self.get_context_data(locked=True))
        data = self.data()
        if request.GET.get('format') == 'xlsx':
            return self.excel(data)
        return self.render_to_response(self.get_context_data(
            references=Reference.objects.all(), **data,
        ))

    def excel(self, data):
        by_sale = ReportTable(
            'Honorarium by sale',
            [Column('Ref'), Column('Voucher'), Column('Sale no.'), Column('Building'), Column('Flat'), Column('Customer'), Column('Status'),
             Column('Honorarium', MONEY), Column('Paid', MONEY), Column('Due', MONEY)],
            [[r['sale'].ref.name if r['sale'].ref else '(no ref)', r['sale'].honorarium_voucher_no, r['sale'].sale_no, r['sale'].project.project_name,
              r['sale'].flat.flat_no, r['sale'].customer.name, r['sale'].get_status_display(), r['honorarium'], r['paid'], r['due']]
             for r in data['rows']],
            ['Total', '', '', '', '', '', '', data['total_honorarium'], data['total_paid'], data['total_due']],
        )
        payments = ReportTable(
            'Honorarium payments',
            [Column('Date', DATE), Column('Voucher'), Column('Ref'), Column('Sale no.'), Column('Flat'), Column('Customer'),
             Column('Paid from'), Column('Amount', MONEY), Column('Confirmed'), Column('Notes')],
            [[p.date, p.reference_no, r['sale'].ref.name if r['sale'].ref else '(no ref)', r['sale'].sale_no, r['sale'].flat.flat_no,
              r['sale'].customer.name, p.account.name, p.amount, 'Yes' if p.is_confirmed else 'No', p.notes]
             for r in data['rows'] for p in r['payments']],
            ['Total', '', '', '', '', '', '', data['total_paid'], '', ''],
        )
        lines = []
        if data['reference']:
            lines.append(f'Ref: {data["reference"].name}')
        if data['date_from'] or data['date_to']:
            lines.append(f'Payments from {data["date_from"] or "the start"} to {data["date_to"] or "today"}')
        if data['only_due']:
            lines.append('Only sales with honorarium still due')
        response = HttpResponse(content_type=XLSX_CONTENT_TYPE)
        response['Content-Disposition'] = 'attachment; filename="honorarium_payments.xlsx"'
        build_xlsx(response, 'Honorarium payments', lines, [by_sale, payments], self.request.user)
        return response


class HonorariumVoucherView(WorkspaceMixin, LoginRequiredMixin, DetailView):
    """A printable voucher for one honorarium payment."""

    model = HonorariumPayment
    template_name = 'sales/honorarium_voucher.html'
    context_object_name = 'payment'
    workspace_lookup = 'sale__project__development'

    def get_queryset(self):
        return super().get_queryset().select_related('account', 'sale', 'sale__ref', 'sale__flat', 'sale__customer', 'sale__project')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        payment = self.object
        # Position as of this payment, not today, so an old voucher stays accurate.
        earlier = payment.sale.honorarium_payments.filter(Q(date__lt=payment.date) | Q(date=payment.date, pk__lte=payment.pk))
        paid = earlier.aggregate(total=Sum('amount'))['total'] or 0
        context['paid_to_date'] = paid
        context['balance_after'] = max(payment.sale.honorarium - paid, 0)
        return context


class _InvoiceView(DetailView):
    model = FlatSale
    template_name = 'sales/sale_invoice.html'
    context_object_name = 'sale'
    shared_link = False

    def get(self, request, *args, **kwargs):
        self.object = self.get_object()
        if request.GET.get('format') != 'pdf':
            return self.render_to_response(self.get_context_data(object=self.object))
        sale = self.object
        response = HttpResponse(content_type='application/pdf')
        response['Content-Disposition'] = f'inline; filename="invoice_{sale.sale_no.replace("/", "-")}.pdf"'
        build_invoice_pdf(response, sale, sale.payments.select_related('account').order_by('payment_date', 'id'))
        if self.shared_link:
            response['X-Robots-Tag'] = 'noindex, nofollow'
            response['Cache-Control'] = 'private, no-store'
        return response

    def get_queryset(self):
        return super().get_queryset().select_related('customer', 'flat', 'project')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['payments'] = self.object.payments.order_by('payment_date', 'id')
        return context


class FlatSaleInvoiceView(WorkspaceMixin, LoginRequiredMixin, _InvoiceView):
    workspace_lookup = 'project__development'


class SharedInvoiceView(_InvoiceView):
    """The invoice behind a private link (sent on WhatsApp), opened without logging in.

    Only the signed, unexpired link works; anything else is a plain 404. It shows exactly the customer-facing invoice."""

    shared_link = True

    def get_object(self, queryset=None):
        pk = sale_pk_from_token(self.kwargs['token'])
        if pk is None:
            raise Http404('This invoice link is not valid any more.')
        return get_object_or_404(self.get_queryset(), pk=pk)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['shared'] = True
        return context

    def render_to_response(self, context, **kwargs):
        response = super().render_to_response(context, **kwargs)
        response['X-Robots-Tag'] = 'noindex, nofollow'
        response['Cache-Control'] = 'private, no-store'
        return response


class CustomerPaymentReceiptView(WorkspaceMixin, LoginRequiredMixin, DetailView):
    model = CustomerPayment
    workspace_lookup = 'sale__project__development'
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
        sales = in_workspace(self.object.sales.exclude(status=FlatSale.Status.CANCELLED).select_related('flat', 'project', 'customer'),
                             self.request, 'project__development')
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
