from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.db.models import Max
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.template.response import TemplateResponse
from django.views import View
from django.views.generic import DetailView, FormView, TemplateView

from core.formatting import DATE, MONEY
from core.workspace import current_development
from reports.excel import XLSX_CONTENT_TYPE, build_xlsx
from reports.tables import Column, ReportTable

from . import services
from .forms import IssueInstallmentForm
from .models import Installment

ZERO = Decimal('0')


def _own_installments(request):
    return Installment.objects.filter(development=current_development(request))


def _sms_summary(counts):
    labels = {'SENT': 'sent', 'LOGGED': 'only logged (no SMS gateway set up)', 'FAILED': 'failed', 'EXCLUDED': 'skipped (excluded from SMS)'}
    return ', '.join(f'{n} {labels[key]}' for key, n in counts.items()) or 'none sent'


class InstallmentListView(LoginRequiredMixin, TemplateView):
    template_name = 'installments/installment_list.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        development = current_development(self.request)
        rows = services.rows_for(development)
        items = []
        for installment in Installment.objects.filter(development=development).select_related('building'):
            own = [r for r in rows if r.charge.installment_id == installment.pk]
            items.append({
                'installment': installment, 'customers': len(own),
                'amount': sum((r.charge.amount for r in own), ZERO), 'paid': sum((r.paid for r in own), ZERO),
                'due': services.due_total(own), 'overdue': services.overdue_total(own),
                'unpaid': sum(1 for r in own if r.due > 0),
            })
        context.update({
            'items': items, 'total_due': services.due_total(rows), 'total_overdue': services.overdue_total(rows),
            'can_issue': self.request.user.has_perm('installments.add_installment'),
        })
        return context


class InstallmentIssueView(PermissionRequiredMixin, FormView):
    """Fill in the installment, look over who will be charged, then confirm."""

    form_class = IssueInstallmentForm
    template_name = 'installments/issue_form.html'
    permission_required = 'installments.add_installment'

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        development = current_development(self.request)
        kwargs['development'] = development
        kwargs['number'] = (Installment.objects.filter(development=development).aggregate(top=Max('number'))['top'] or 0) + 1
        return kwargs

    def form_valid(self, form):
        development = current_development(self.request)
        data = form.cleaned_data
        if self.request.POST.get('confirm') != '1':
            rows, skipped = services.preview(development, data['building'], data['basis'], data['value'])
            hidden = [(k, v) for k, v in self.request.POST.items() if k not in ('csrfmiddlewaretoken', 'confirm')]
            context = self.get_context_data(
                form=form, rows=rows, skipped=skipped, hidden=hidden,
                total=sum((amount for _, amount, _ in rows), ZERO), capped=sum(1 for *_, capped in rows if capped),
            )
            return TemplateResponse(self.request, 'installments/issue_preview.html', context)

        installment = services.issue(
            development, self.request.user, data['title'], data['due_date'], data['basis'], data['value'],
            building=data['building'], notes=data['notes'],
        )
        charged = installment.issued_charges
        total = sum((c.amount for c in charged), ZERO)
        if not charged:
            messages.warning(self.request, f'{installment.title} was issued, but there was nobody to charge.')
            return redirect(installment)
        text = f'{installment.title} issued: Tk {total:,.2f} added as due on {len(charged)} customer account(s), payable by {installment.due_date:%d %b %Y}.'
        if data['send_sms']:
            counts = services.notify_all(charged, self.request.user)
            text += f' SMS: {_sms_summary(counts)}.'
            if set(counts) <= {'LOGGED'}:
                messages.warning(self.request, text + ' No SMS gateway is set up, so the messages are only in the SMS log.')
            else:
                messages.success(self.request, text)
        else:
            messages.success(self.request, text + ' No SMS was sent.')
        return redirect(installment)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['development'] = current_development(self.request)
        return context


class InstallmentDetailView(LoginRequiredMixin, DetailView):
    """Who owes what on one installment, what they have paid, and whether the SMS went out."""

    model = Installment
    template_name = 'installments/installment_detail.html'
    context_object_name = 'object'

    def get_queryset(self):
        return _own_installments(self.request).select_related('building', 'issued_by')

    def rows(self):
        rows = services.rows_for(self.object.development, self.object)
        show = self.request.GET.get('show')
        if show == 'unpaid':
            rows = [r for r in rows if r.due > 0]
        elif show == 'overdue':
            rows = [r for r in rows if r.status == services.OVERDUE]
        elif show == 'paid':
            rows = [r for r in rows if r.status == services.PAID]
        return rows

    def get(self, request, *args, **kwargs):
        self.object = self.get_object()
        if request.GET.get('format') == 'xlsx':
            return self.excel()
        return self.render_to_response(self.get_context_data(object=self.object))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        everyone = services.rows_for(self.object.development, self.object)
        context.update({
            'rows': self.rows(), 'show': self.request.GET.get('show', ''),
            'total': sum((r.charge.amount for r in everyone), ZERO), 'paid': sum((r.paid for r in everyone), ZERO),
            'due': services.due_total(everyone), 'overdue': services.overdue_total(everyone),
            'unpaid_count': sum(1 for r in everyone if r.due > 0), 'today': timezone.localdate(),
            'can_send': self.request.user.has_perm('installments.add_installment'),
            'can_withdraw': self.request.user.has_perm('installments.delete_installment') and not any(r.paid > 0 for r in everyone),
        })
        return context

    def excel(self):
        installment = self.object
        rows = self.rows()
        table = ReportTable(
            installment.title,
            [Column('Customer ID'), Column('Customer'), Column('Phone'), Column('Building'), Column('Flat'), Column('Deadline', DATE),
             Column('Amount', MONEY), Column('Paid', MONEY), Column('Due', MONEY), Column('Status'), Column('SMS sent')],
            [[r.sale.customer.customer_code, r.sale.customer.name, r.sale.customer.phone, r.sale.project.project_name,
              r.sale.flat.flat_no, installment.due_date, r.charge.amount, r.paid, r.due, r.status,
              f'{r.charge.notified_at:%d %b %Y %H:%M}' if r.charge.notified_at else 'No'] for r in rows],
            ['Total', '', '', '', '', '', sum((r.charge.amount for r in rows), ZERO), sum((r.paid for r in rows), ZERO),
             services.due_total(rows), '', ''],
        )
        lines = [f'Project: {installment.development.name}', f'Payment deadline: {installment.due_date:%d %b %Y}']
        response = HttpResponse(content_type=XLSX_CONTENT_TYPE)
        response['Content-Disposition'] = f'attachment; filename="installment_{installment.development.code}_{installment.number}.xlsx"'
        build_xlsx(response, installment.title, lines, [table], self.request.user)
        return response


class InstallmentSendSmsView(PermissionRequiredMixin, View):
    """POST-only: send the installment SMS again to every customer who has not paid it in full."""

    http_method_names = ['post']
    permission_required = 'installments.add_installment'

    def post(self, request, pk):
        installment = get_object_or_404(_own_installments(request), pk=pk)
        rows = [r for r in services.rows_for(installment.development, installment) if r.due > 0]
        if not rows:
            messages.info(request, 'Everybody has paid this installment in full: nothing to send.')
        else:
            counts = services.notify_all([r.charge for r in rows], request.user)
            messages.success(request, f'SMS to {len(rows)} customer(s) who still owe {installment.title}: {_sms_summary(counts)}.')
        return redirect(installment)


class InstallmentWithdrawView(PermissionRequiredMixin, View):
    """POST-only: take an installment back (only while nobody has paid anything towards it)."""

    http_method_names = ['post']
    permission_required = 'installments.delete_installment'

    def post(self, request, pk):
        installment = get_object_or_404(_own_installments(request), pk=pk)
        title = installment.title
        if services.withdraw(installment):
            messages.success(request, f'{title} was withdrawn: it is no longer due on any customer account.')
            return redirect('installments:list')
        messages.error(request, f'{title} cannot be withdrawn: customers have already paid towards it.')
        return redirect(installment)
