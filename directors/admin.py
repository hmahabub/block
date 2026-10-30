from django.contrib import admin

from .models import Director, DirectorTransaction


@admin.register(Director)
class DirectorAdmin(admin.ModelAdmin):
    list_display = ('director_code', 'name', 'phone', 'is_active')
    search_fields = ('director_code', 'name', 'phone')


@admin.register(DirectorTransaction)
class DirectorTransactionAdmin(admin.ModelAdmin):
    list_display = ('date', 'director', 'development', 'kind', 'amount', 'account', 'confirmed_at')
    list_filter = ('kind', 'development')
