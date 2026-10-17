from django.contrib import admin

from .models import SmsLog, WhatsAppShare


@admin.register(SmsLog)
class SmsLogAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'customer', 'phone', 'kind', 'status')
    list_filter = ('kind', 'status')
    search_fields = ('phone', 'customer__name', 'message')
    readonly_fields = ('customer', 'phone', 'kind', 'message', 'status', 'error', 'sent_by', 'created_at')

    def has_add_permission(self, request):
        return False


@admin.register(WhatsAppShare)
class WhatsAppShareAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'sale', 'customer', 'phone', 'opened_by')
    readonly_fields = ('sale', 'customer', 'phone', 'opened_by', 'created_at')

    def has_add_permission(self, request):
        return False
