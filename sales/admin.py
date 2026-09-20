from django.contrib import admin

from .models import CustomerPayment, FlatSale


@admin.register(FlatSale)
class FlatSaleAdmin(admin.ModelAdmin):
    list_display = ('sale_no', 'flat', 'customer', 'net_sale_value', 'received_amount', 'receivable_amount', 'status')
    list_filter = ('status', 'project')
    search_fields = ('sale_no', 'customer__name', 'flat__flat_no')


@admin.register(CustomerPayment)
class CustomerPaymentAdmin(admin.ModelAdmin):
    list_display = ('customer', 'sale', 'amount', 'payment_date', 'payment_method')
    list_filter = ('payment_method',)
    search_fields = ('customer__name', 'reference_no')
