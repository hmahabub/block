from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.urls import reverse

from core.models import ConfirmableModel


class Account(models.Model):
    """A bank account or a cash box (e.g. Bank 1, Bank 2, Petty cash).

    The single book is a view over these accounts: every payment in or out is collected from
    its source module (customer payments, cost entries, honorarium, refunds) or from an internal
    transfer. Nothing is typed into the book itself.
    """

    class AccountType(models.TextChoices):
        BANK = 'BANK', 'Bank'
        CASH = 'CASH', 'Cash'

    class BankKind(models.TextChoices):
        CURRENT = 'CURRENT', 'Current Account'
        SAVINGS = 'SAVINGS', 'Savings Account'
        FIXED = 'FIXED', 'Fixed Deposit'

    name = models.CharField(max_length=100, help_text='e.g. Bank 1, Bank 2, Petty cash')
    account_type = models.CharField(max_length=10, choices=AccountType.choices, default=AccountType.BANK)
    bank_name = models.CharField(max_length=100, blank=True)
    account_number = models.CharField(max_length=50, blank=True)
    branch = models.CharField(max_length=100, blank=True)
    bank_kind = models.CharField('Account kind', max_length=20, choices=BankKind.choices, blank=True)
    opening_balance = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['account_type', 'name']
        permissions = [('confirm_entries', 'Can confirm book entries')]

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse('books:ledger', kwargs={'pk': self.pk})

    @property
    def is_cash(self):
        return self.account_type == self.AccountType.CASH

    @property
    def detail(self):
        if self.is_cash:
            return 'Cash'
        parts = [self.bank_name, self.account_number]
        return ' · '.join(part for part in parts if part) or 'Bank'


class Transfer(ConfirmableModel):
    """Money moved from one of our accounts to another (e.g. bank to petty cash)."""

    date = models.DateField()
    from_account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name='transfers_out')
    to_account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name='transfers_in')
    amount = models.DecimalField(max_digits=14, decimal_places=2, validators=[MinValueValidator(0.01)])
    notes = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-date', '-id']

    def __str__(self):
        return f'{self.reference_no}: {self.from_account} → {self.to_account} ({self.amount})'

    @property
    def reference_no(self):
        return f'TR-{self.pk:05d}'

    def clean(self):
        if self.from_account_id and self.from_account_id == self.to_account_id:
            raise ValidationError('Choose two different accounts for a transfer.')
