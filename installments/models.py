"""Installments: after construction starts, customers pay for their flats in installments.

Issuing an installment adds an amount as due on the account of every customer who booked a flat in the project, with a
payment deadline. When a payment is recorded, the person says whether it is for the flat booking or for an installment
(and which one); only payments made for installments pay them off.

    Installment        one call for payment on a project (a title, a deadline, how the amount is worked out)
    InstallmentCharge  what one customer's booking owes on it
"""
from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.urls import reverse
from django.utils import timezone


class Installment(models.Model):
    class Basis(models.TextChoices):
        FIXED = 'FIXED', 'The same amount for every flat'
        PERCENT = 'PERCENT', 'A percentage of each sale value'

    development = models.ForeignKey('projects.Development', on_delete=models.PROTECT, related_name='installments')
    building = models.ForeignKey(
        'projects.Project', null=True, blank=True, on_delete=models.PROTECT, related_name='installments',
        help_text='Leave empty for every building of the project.',
    )
    number = models.PositiveIntegerField(editable=False)
    title = models.CharField(max_length=120)
    due_date = models.DateField('Payment deadline')
    basis = models.CharField(max_length=10, choices=Basis.choices, default=Basis.FIXED)
    value = models.DecimalField(
        'Amount / percentage', max_digits=14, decimal_places=2, validators=[MinValueValidator(0.01)],
        help_text='Taka per flat, or the percentage of the sale value, as chosen above.',
    )
    notes = models.TextField(blank=True)
    issued_on = models.DateField(default=timezone.localdate, editable=False)
    issued_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, editable=False, on_delete=models.SET_NULL, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-development_id', '-number']
        constraints = [models.UniqueConstraint(fields=['development', 'number'], name='unique_installment_number_per_project')]

    def __str__(self):
        return f'{self.title} ({self.development.name})'

    def get_absolute_url(self):
        return reverse('installments:detail', kwargs={'pk': self.pk})

    @property
    def amount_text(self):
        return f'{self.value:,.2f}%' if self.basis == self.Basis.PERCENT else f'Tk {self.value:,.2f}'


class InstallmentCharge(models.Model):
    """What one booking owes on one installment."""

    installment = models.ForeignKey(Installment, on_delete=models.CASCADE, related_name='charges')
    sale = models.ForeignKey('sales.FlatSale', on_delete=models.CASCADE, related_name='installment_charges')
    amount = models.DecimalField(max_digits=14, decimal_places=2, validators=[MinValueValidator(0.01)])
    notified_at = models.DateTimeField(null=True, blank=True, editable=False, help_text='When the customer was last sent the SMS.')

    class Meta:
        ordering = ['installment__due_date', 'installment__number', 'id']
        constraints = [models.UniqueConstraint(fields=['installment', 'sale'], name='one_charge_per_sale_per_installment')]

    def __str__(self):
        return f'{self.installment.title}: {self.sale.sale_no} {self.amount}'

