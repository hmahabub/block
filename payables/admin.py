from django.contrib import admin

from .models import SupplierPayment


@admin.register(SupplierPayment)
class SupplierPaymentAdmin(admin.ModelAdmin):
    list_display = ('supplier', 'project_cost', 'amount', 'payment_date', 'payment_method')
    list_filter = ('payment_method',)
    search_fields = ('supplier__name', 'reference_no')
