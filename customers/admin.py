from django.contrib import admin

from .models import Customer


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ('customer_code', 'name', 'phone', 'email')
    search_fields = ('customer_code', 'name', 'phone', 'email')
