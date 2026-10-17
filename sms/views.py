from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.core.exceptions import PermissionDenied
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect
from django.views import View
from django.views.generic import ListView, TemplateView

from core.utils import int_or_none
from customers.models import Customer
from projects.models import Project
from sales.models import FlatSale

from .backends import SmsError
from .models import SmsLog, WhatsAppShare
from .whatsapp import has_whatsapp, invoice_message, invoice_url, whatsapp_link
from .services import backend_description, customers_with_dues, gateway_balance, reminder_message, send_reminders


class ReminderView(PermissionRequiredMixin, TemplateView):
    """Balance reminders go out only when someone ticks customers here and presses send."""

    template_name = 'sms/reminders.html'
    permission_required = 'sms.add_smslog'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        customers = customers_with_dues()
        last = {}
        for log in SmsLog.objects.filter(kind=SmsLog.Kind.REMINDER, customer__in=customers):
            last.setdefault(log.customer_id, log.created_at)
        for customer in customers:
            customer.last_reminder = last.get(customer.pk)
            customer.preview = reminder_message(customer)
        context['customers'] = customers
        context['backend'] = backend_description()
        return context


class SendRemindersView(PermissionRequiredMixin, View):
    http_method_names = ['post']
    permission_required = 'sms.add_smslog'

    def post(self, request):
        ids = [pk for pk in request.POST.getlist('customers') if pk.isdigit()]
        customers = Customer.objects.filter(pk__in=ids)
        if not customers:
            messages.warning(request, 'Tick at least one customer first.')
            return redirect('sms:reminders')
        sent, skipped = send_reminders(customers, request.user)
        if sent:
            messages.success(request, f'{len(sent)} reminder(s) processed. See the SMS log for delivery status.')
        if skipped:
            names = ', '.join(c.name for c in skipped)
            messages.warning(request, f'Skipped (excluded from SMS or nothing due): {names}')
        return redirect('sms:log')


class WhatsAppInvoicesView(PermissionRequiredMixin, TemplateView):
    """Customers with a WhatsApp number, each with a button that opens WhatsApp ready to send their invoice."""

    template_name = 'sms/whatsapp_invoices.html'
    permission_required = 'sms.add_whatsappshare'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        project = Project.objects.filter(pk=int_or_none(self.request.GET.get('project'))).first()
        sales = FlatSale.objects.exclude(status=FlatSale.Status.CANCELLED).select_related('customer', 'flat', 'project')
        if project:
            sales = sales.filter(project=project)
        last_sent = {}
        for share in WhatsAppShare.objects.filter(sale__in=sales):
            last_sent.setdefault(share.sale_id, share)
        ready, missing = [], []
        for sale in sales.order_by('customer__name', 'sale_no'):
            sale.last_share = last_sent.get(sale.pk)
            (ready if has_whatsapp(sale.customer) else missing).append(sale)
        context.update({
            'ready': ready, 'missing': missing, 'projects': Project.objects.order_by('project_name'),
            'selected_project': project,
        })
        return context


class WhatsAppSendView(PermissionRequiredMixin, View):
    """Record that WhatsApp was opened for this sale's invoice, then go to WhatsApp with the message ready."""

    http_method_names = ['post']
    permission_required = 'sms.add_whatsappshare'

    def post(self, request, pk):
        sale = get_object_or_404(FlatSale.objects.select_related('customer', 'flat', 'project'), pk=pk)
        back = request.POST.get('next') or ''
        back = back if back.startswith('/') and not back.startswith('//') else '/sms/whatsapp/'
        if sale.status == FlatSale.Status.CANCELLED:
            messages.error(request, f'{sale.sale_no} is cancelled; there is no invoice to send.')
            return redirect(back)
        if not has_whatsapp(sale.customer):
            messages.error(request, f'{sale.customer.name} has no WhatsApp number. Add one on the customer page first.')
            return redirect(back)
        WhatsAppShare.objects.create(
            sale=sale, customer=sale.customer, phone=sale.customer.whatsapp_no, opened_by=request.user,
        )
        text = invoice_message(sale, invoice_url(request, sale))
        return HttpResponseRedirect(whatsapp_link(sale.customer.whatsapp_no, text))


class SmsBalanceView(PermissionRequiredMixin, View):
    """Ask the SMS gateway how much balance is left."""

    http_method_names = ['get']
    permission_required = 'sms.add_smslog'

    def get(self, request):
        try:
            messages.info(request, f'SMS balance - {gateway_balance()}')
        except SmsError as error:
            messages.error(request, f'Could not read the SMS balance: {error}')
        return redirect('sms:log')


class SmsLogView(LoginRequiredMixin, ListView):
    model = SmsLog
    template_name = 'sms/log.html'
    context_object_name = 'object_list'
    paginate_by = 50

    def get_queryset(self):
        queryset = super().get_queryset().select_related('customer')
        customer = self.request.GET.get('customer')
        if customer and customer.isdigit():
            queryset = queryset.filter(customer_id=customer)
        return queryset
