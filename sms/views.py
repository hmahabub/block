from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.shortcuts import redirect
from django.views import View
from django.views.generic import ListView, TemplateView

from customers.models import Customer

from .backends import SmsError
from .models import SmsLog
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
