from django import forms
from django.utils import timezone

from .models import Account, Transfer


class AccountForm(forms.ModelForm):
    class Meta:
        model = Account
        fields = [
            'name', 'account_type', 'bank_name', 'account_number', 'branch', 'bank_kind',
            'opening_balance', 'is_active', 'notes',
        ]
        widgets = {'notes': forms.Textarea(attrs={'rows': 2})}


class TransferForm(forms.ModelForm):
    """Move money between two of our own accounts (bank to bank, bank to petty cash, ...)."""

    class Meta:
        model = Transfer
        fields = ['date', 'from_account', 'to_account', 'amount', 'notes']
        widgets = {'date': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d')}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        accounts = Account.objects.filter(is_active=True)
        self.fields['from_account'].queryset = accounts
        self.fields['to_account'].queryset = accounts
        if not self.instance.pk:
            self.fields['date'].initial = timezone.localdate()
