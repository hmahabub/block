from django.core.validators import RegexValidator
from django.db import models
from django.urls import reverse

from core.numbering import generate_year_code

phone_regex = RegexValidator(
    regex=r'^\+?1?\d{9,15}$',
    message="Phone number must be in format: '+999999999'. Up to 15 digits allowed.",
)


class Supplier(models.Model):
    supplier_code = models.CharField(max_length=20, unique=True, editable=False)
    name = models.CharField('Supplier / Contractor Name', max_length=150)
    contact_person = models.CharField(max_length=100, blank=True)
    phone = models.CharField(validators=[phone_regex], max_length=17, blank=True)
    address = models.TextField(blank=True)
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
            self.supplier_code = generate_year_code('supplier', 'S')
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse('suppliers:detail', kwargs={'pk': self.pk})

    @property
    def total_payable(self):
        return sum((cost.payable_amount for cost in self.project_costs.all()), start=0)
