from django import forms
from django.utils import timezone

from .models import BankAccount, BankBook, CashBook


class CashBookForm(forms.ModelForm):
    class Meta:
        model = CashBook
        fields = ['date', 'transaction_type', 'amount', 'particulars']
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.instance.pk:
            self.fields['date'].initial = timezone.now().date()


class BankBookForm(forms.ModelForm):
    class Meta:
        model = BankBook
        fields = ['bank_account', 'date', 'transaction_type', 'amount', 'particulars', 'cheque_no', 'cheque_date']
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date'}),
            'cheque_date': forms.DateInput(attrs={'type': 'date'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['bank_account'].queryset = BankAccount.objects.filter(is_active=True)
        if not self.instance.pk:
            self.fields['date'].initial = timezone.now().date()


class BankAccountForm(forms.ModelForm):
    class Meta:
        model = BankAccount
        fields = ['name', 'account_number', 'bank_name', 'branch', 'account_type', 'opening_balance', 'is_active', 'notes']

    def save(self, commit=True):
        instance = super().save(commit=False)
        if not instance.pk:
            instance.current_balance = instance.opening_balance
        if commit:
            instance.save()
        return instance
