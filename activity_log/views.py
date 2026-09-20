from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import ListView

from .models import ActivityLog


class ActivityLogListView(LoginRequiredMixin, ListView):
    model = ActivityLog
    template_name = 'activity_log/activitylog_list.html'
    context_object_name = 'logs'
    paginate_by = 30

    def get_queryset(self):
        queryset = super().get_queryset().select_related('user')
        user_id = self.request.GET.get('user')
        if user_id:
            queryset = queryset.filter(user_id=user_id)
        return queryset
