from django.contrib import admin

from .models import SmsLog


@admin.register(SmsLog)
class SmsLogAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'customer', 'phone', 'kind', 'status')
    list_filter = ('kind', 'status')
    search_fields = ('phone', 'customer__name', 'message')
    readonly_fields = ('customer', 'phone', 'kind', 'message', 'status', 'error', 'sent_by', 'created_at')

    def has_add_permission(self, request):
        return False
