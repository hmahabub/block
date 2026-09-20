from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Sum


class BankAccount(models.Model):
    class AccountType(models.TextChoices):
        CURRENT = 'CURRENT', 'Current Account'
        SAVINGS = 'SAVINGS', 'Savings Account'
        FIXED = 'FIXED', 'Fixed Deposit'

    name = models.CharField(max_length=100)
    account_number = models.CharField(max_length=50)
    bank_name = models.CharField(max_length=100)
    branch = models.CharField(max_length=100, blank=True)
    account_type = models.CharField(max_length=20, choices=AccountType.choices, default=AccountType.CURRENT)
    opening_balance = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    current_balance = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['bank_name', 'name']

    def __str__(self):
        return f'{self.bank_name} - {self.name} ({self.account_number})'

    def update_balance(self):
        totals = self.transactions.aggregate(
            credit=Sum('amount', filter=models.Q(transaction_type='CREDIT')),
            debit=Sum('amount', filter=models.Q(transaction_type='DEBIT')),
        )
        self.current_balance = self.opening_balance + (totals['credit'] or 0) - (totals['debit'] or 0)
        self.save(update_fields=['current_balance'])


class LedgerEntryBase(models.Model):
    TRANSACTION_TYPES = (
        ('CREDIT', 'Credit'),
        ('DEBIT', 'Debit'),
    )

    date = models.DateField()
    transaction_type = models.CharField(max_length=10, choices=TRANSACTION_TYPES)
    amount = models.DecimalField(max_digits=14, decimal_places=2, validators=[MinValueValidator(0.01)])
    particulars = models.CharField(max_length=300)
    current_balance = models.DecimalField(max_digits=14, decimal_places=2, default=0, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
        ordering = ['-date', '-id']

    def __str__(self):
        return f'{self.amount} ({self.date})'


class CashBook(LedgerEntryBase):
    class Meta(LedgerEntryBase.Meta):
        verbose_name = 'Cash Book Entry'
        verbose_name_plural = 'Cash Book Entries'

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        CashBook.recompute_balances()

    def delete(self, *args, **kwargs):
        super().delete(*args, **kwargs)
        CashBook.recompute_balances()

    @classmethod
    def recompute_balances(cls):
        """Iteratively walk every entry in date order and fix its running balance.

        Replaces inspcta's recursive cascade (which risked hitting Python's
        recursion limit on a long-running book and re-saved every later row
        one at a time). This does one query, one bulk_update, no recursion.
        """
        balance = 0
        updates = []
        for entry in cls.objects.order_by('date', 'id'):
            balance += entry.amount if entry.transaction_type == 'CREDIT' else -entry.amount
            if entry.current_balance != balance:
                entry.current_balance = balance
                updates.append(entry)
        if updates:
            cls.objects.bulk_update(updates, ['current_balance'])


class BankBook(LedgerEntryBase):
    bank_account = models.ForeignKey(BankAccount, on_delete=models.PROTECT, related_name='transactions')
    cheque_no = models.CharField(max_length=100, blank=True)
    cheque_date = models.DateField(null=True, blank=True)

    class Meta(LedgerEntryBase.Meta):
        verbose_name = 'Bank Book Entry'
        verbose_name_plural = 'Bank Book Entries'

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        BankBook.recompute_balances(self.bank_account_id)

    def delete(self, *args, **kwargs):
        account_id = self.bank_account_id
        super().delete(*args, **kwargs)
        BankBook.recompute_balances(account_id)

    @classmethod
    def recompute_balances(cls, bank_account_id):
        account = BankAccount.objects.get(pk=bank_account_id)
        balance = account.opening_balance
        updates = []
        for entry in cls.objects.filter(bank_account_id=bank_account_id).order_by('date', 'id'):
            balance += entry.amount if entry.transaction_type == 'CREDIT' else -entry.amount
            if entry.current_balance != balance:
                entry.current_balance = balance
                updates.append(entry)
        if updates:
            cls.objects.bulk_update(updates, ['current_balance'])
        account.update_balance()
