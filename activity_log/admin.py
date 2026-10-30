from django.contrib import admin

from .models import ActivityLog


@admin.register(ActivityLog)
class ActivityLogAdmin(admin.ModelAdmin):
    """Read-only: the audit trail is a record, so nobody can add, edit or delete lines, not even in the admin."""

    list_display = ('created_at', 'user', 'action', 'model_name', 'object_repr', 'ip_address')
    list_filter = ('action', 'model_name', 'user')
    search_fields = ('object_repr', 'object_id', 'user__username')
    readonly_fields = [f.name for f in ActivityLog._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
