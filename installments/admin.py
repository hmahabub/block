from django.contrib import admin

from .models import Installment, InstallmentCharge


class ChargeInline(admin.TabularInline):
    model = InstallmentCharge
    extra = 0
    readonly_fields = ('sale', 'amount', 'notified_at')
    can_delete = False


@admin.register(Installment)
class InstallmentAdmin(admin.ModelAdmin):
    list_display = ('title', 'development', 'due_date', 'basis', 'value', 'issued_on')
    inlines = [ChargeInline]
