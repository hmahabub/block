import datetime

from django.apps import apps
from django.contrib.auth import get_user_model
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Q
from django.http import HttpResponse
from django.views.generic import ListView

from core.formatting import DATE
from core.utils import int_or_none
from reports.excel import XLSX_CONTENT_TYPE, build_xlsx
from reports.tables import Column, ReportTable

from .models import ActivityLog

EXPORT_LIMIT = 5000


def _date(value):
    try:
        return datetime.date.fromisoformat(value) if value else None
    except ValueError:
        return None


class AuditTrailView(LoginRequiredMixin, ListView):
    """The audit trail: filter by who, what kind of change, which kind of record, one record, or a date range."""

    model = ActivityLog
    template_name = 'activity_log/activitylog_list.html'
    context_object_name = 'logs'
    paginate_by = 50

    def filtered(self):
        params = self.request.GET
        queryset = ActivityLog.objects.select_related('user')
        user_id = int_or_none(params.get('user'))
        if user_id:
            queryset = queryset.filter(user_id=user_id)
        elif params.get('user') == 'system':
            queryset = queryset.filter(user__isnull=True)
        if params.get('action') in dict(ActivityLog.ACTIONS):
            queryset = queryset.filter(action=params['action'])
        if params.get('type') and '.' in params['type']:
            app_label, _, model_name = params['type'].partition('.')
            queryset = queryset.filter(app_label=app_label, model_name=model_name)
        if params.get('app') and params.get('model') and params.get('object'):   # the history of one record
            queryset = queryset.filter(app_label=params['app'], model_name=params['model'], object_id=params['object'])
        q = (params.get('q') or '').strip()
        if q:
            queryset = queryset.filter(Q(object_repr__icontains=q) | Q(object_id=q) | Q(user__username__icontains=q))
        date_from, date_to = _date(params.get('date_from')), _date(params.get('date_to'))
        if date_from:
            queryset = queryset.filter(created_at__date__gte=date_from)
        if date_to:
            queryset = queryset.filter(created_at__date__lte=date_to)
        return queryset

    def get_queryset(self):
        return self.filtered()

    def get(self, request, *args, **kwargs):
        if request.GET.get('format') == 'xlsx':
            return self.excel()
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        params = self.request.GET
        kinds = []
        for app_label, model_name in ActivityLog.objects.values_list('app_label', 'model_name').distinct().order_by('app_label', 'model_name'):
            try:
                label = str(apps.get_model(app_label, model_name)._meta.verbose_name).title()
            except LookupError:
                label = model_name
            kinds.append((f'{app_label}.{model_name}', label))
        context.update({
            'users': get_user_model().objects.filter(activity_logs__isnull=False).distinct().order_by('username'),
            'kinds': sorted(kinds, key=lambda item: item[1]), 'actions': ActivityLog.ACTIONS,
            'one_record': bool(params.get('app') and params.get('model') and params.get('object')),
            'date_from': _date(params.get('date_from')), 'date_to': _date(params.get('date_to')),
        })
        return context

    def excel(self):
        logs = list(self.filtered()[:EXPORT_LIMIT])
        rows = []
        for log in logs:
            changes = '; '.join(
                f'{label}: {old if old is not None else "-"} -> {new if new is not None else "-"}'
                for label, old, new in log.change_rows()
            )
            rows.append([
                log.created_at.replace(tzinfo=None), log.user.get_full_name() or log.user.username if log.user else 'System',
                log.get_action_display(), log.model_label, log.object_repr, log.object_id, changes, log.ip_address or '',
            ])
        table = ReportTable(
            'Audit trail',
            [Column('When', DATE), Column('User'), Column('Action'), Column('Record type'), Column('Record'), Column('Id'),
             Column('What changed'), Column('IP address')],
            rows, note=f'Showing up to {EXPORT_LIMIT} newest entries matching the filters.' if len(logs) == EXPORT_LIMIT else '',
        )
        response = HttpResponse(content_type=XLSX_CONTENT_TYPE)
        response['Content-Disposition'] = 'attachment; filename="audit_trail.xlsx"'
        build_xlsx(response, 'Audit Trail', [f'{len(logs)} entries'], [table], self.request.user)
        return response


# kept under its old name so existing links and imports keep working
ActivityLogListView = AuditTrailView
