from django.core.validators import RegexValidator
from django.db import models
from django.urls import reverse

from core.numbering import generate_dashed_code
from core.phone import normalize_phone

phone_regex = RegexValidator(
    regex=r'^\+?1?\d{9,15}$',
    message="Phone number must be in format: '+999999999'. Up to 15 digits allowed.",
)


class Supplier(models.Model):
    supplier_code = models.CharField(max_length=20, unique=True, editable=False)
    name = models.CharField('Company name', max_length=150)
    owner_name = models.CharField(max_length=100, blank=True)
    phone = models.CharField(validators=[phone_regex], max_length=17, blank=True,
                             help_text='+88 is added automatically to local numbers.')
    email = models.EmailField(blank=True)
    tin = models.CharField('TIN', max_length=30, blank=True)
    address = models.TextField(blank=True)
    bank_account = models.CharField(max_length=150, blank=True, help_text='Bank, account name and number.')
    cost_category = models.ForeignKey(
        'costing.CostCategory', null=True, blank=True, on_delete=models.SET_NULL, related_name='suppliers',
        verbose_name='Type', help_text='The kind of work this supplier does (same list as the cost categories).',
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        indexes = [
            models.Index(fields=['name']),
            models.Index(fields=['supplier_code']),
        ]

    def __str__(self):
        return f'{self.supplier_code} - {self.name}'

    def save(self, *args, **kwargs):
        if not self.supplier_code:
            self.supplier_code = generate_dashed_code('supplier', 'S')
        self.phone = normalize_phone(self.phone)
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse('suppliers:detail', kwargs={'pk': self.pk})

    @property
    def total_cost(self):
        return sum((cost.amount for cost in self.project_costs.all()), start=0)
