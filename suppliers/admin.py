from django.contrib import admin

from .models import Supplier


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ('supplier_code', 'name', 'owner_name', 'cost_category', 'phone')
    search_fields = ('supplier_code', 'name', 'phone')
