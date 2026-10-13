from django.contrib import admin

from .models import CustomerPayment, FlatSale, HonorariumPayment, RefundPayment, Reference


@admin.register(FlatSale)
class FlatSaleAdmin(admin.ModelAdmin):
    list_display = ('sale_no', 'flat', 'customer', 'ref', 'sale_value', 'net_value', 'received_amount', 'receivable_amount', 'status')
    list_filter = ('status', 'project')
    search_fields = ('sale_no', 'customer__name', 'flat__flat_no')


@admin.register(CustomerPayment)
class CustomerPaymentAdmin(admin.ModelAdmin):
    list_display = ('customer', 'sale', 'amount', 'payment_date', 'account', 'confirmed_at')
    list_filter = ('account',)
    search_fields = ('customer__name', 'reference_no')


@admin.register(Reference)
class ReferenceAdmin(admin.ModelAdmin):
    list_display = ('name', 'phone')
    search_fields = ('name', 'phone')


admin.site.register(HonorariumPayment)
admin.site.register(RefundPayment)
