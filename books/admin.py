from django.contrib import admin

from .models import Account, Transfer


@admin.register(Account)
class AccountAdmin(admin.ModelAdmin):
    list_display = ('name', 'account_type', 'bank_name', 'account_number', 'opening_balance', 'is_active')
    list_filter = ('account_type', 'is_active')


@admin.register(Transfer)
class TransferAdmin(admin.ModelAdmin):
    list_display = ('date', 'from_account', 'to_account', 'amount', 'confirmed_at')
    list_filter = ('from_account', 'to_account')
