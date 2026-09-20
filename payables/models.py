from django.core.validators import MinValueValidator
from django.db import models


class SupplierPayment(models.Model):
    class Method(models.TextChoices):
        CASH = 'CASH', 'Cash'
        BANK = 'BANK', 'Bank'
        CHEQUE = 'CHEQUE', 'Cheque'
        OTHER = 'OTHER', 'Other'

    project_cost = models.ForeignKey('costing.ProjectCost', on_delete=models.CASCADE, related_name='payments')
    supplier = models.ForeignKey('suppliers.Supplier', on_delete=models.PROTECT, related_name='payments')
    payment_date = models.DateField()
    amount = models.DecimalField(max_digits=14, decimal_places=2, validators=[MinValueValidator(0.01)])
    payment_method = models.CharField(max_length=10, choices=Method.choices, default=Method.BANK)
    reference_no = models.CharField(max_length=100, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-payment_date', '-id']
        verbose_name = 'Supplier Payment'

    def __str__(self):
        return f'{self.supplier} - {self.amount} ({self.payment_date})'

    def save(self, *args, **kwargs):
        if not self.supplier_id and self.project_cost_id:
            self.supplier = self.project_cost.supplier
        super().save(*args, **kwargs)
        self.project_cost.recalc_paid_amount()

    def delete(self, *args, **kwargs):
        project_cost = self.project_cost
        super().delete(*args, **kwargs)
        project_cost.recalc_paid_amount()
