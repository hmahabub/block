from django.contrib import admin

from .models import BankAccount, BankBook, CashBook


@admin.register(BankAccount)
class BankAccountAdmin(admin.ModelAdmin):
    list_display = ('bank_name', 'name', 'account_number', 'account_type', 'current_balance', 'is_active')
    list_filter = ('account_type', 'is_active')


@admin.register(CashBook)
class CashBookAdmin(admin.ModelAdmin):
    list_display = ('date', 'transaction_type', 'amount', 'particulars', 'current_balance')
    list_filter = ('transaction_type',)


@admin.register(BankBook)
class BankBookAdmin(admin.ModelAdmin):
    list_display = ('date', 'bank_account', 'transaction_type', 'amount', 'particulars', 'current_balance')
    list_filter = ('transaction_type', 'bank_account')
