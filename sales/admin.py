from django.contrib import admin

from .models import ApartmentSale, CustomerPayment


@admin.register(ApartmentSale)
class ApartmentSaleAdmin(admin.ModelAdmin):
    list_display = ('sale_no', 'apartment', 'customer', 'net_sale_value', 'received_amount', 'receivable_amount', 'status')
    list_filter = ('status', 'project')
    search_fields = ('sale_no', 'customer__name', 'apartment__apartment_no')


@admin.register(CustomerPayment)
class CustomerPaymentAdmin(admin.ModelAdmin):
    list_display = ('customer', 'sale', 'amount', 'payment_date', 'payment_method')
    list_filter = ('payment_method',)
    search_fields = ('customer__name', 'reference_no')
