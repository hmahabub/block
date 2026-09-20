from django.core.validators import RegexValidator
from django.db import models
from django.urls import reverse

from core.numbering import generate_year_code

phone_regex = RegexValidator(
    regex=r'^\+?1?\d{9,15}$',
    message="Phone number must be in format: '+999999999'. Up to 15 digits allowed.",
)


class Customer(models.Model):
    customer_code = models.CharField(max_length=20, unique=True, editable=False)
    name = models.CharField('Customer Name', max_length=150)
    phone = models.CharField(validators=[phone_regex], max_length=17, blank=True)
    email = models.EmailField(blank=True)
    address = models.TextField(blank=True)
    identification_no = models.CharField('NID / Passport No.', max_length=50, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        indexes = [
            models.Index(fields=['name']),
            models.Index(fields=['customer_code']),
        ]

    def __str__(self):
        return f'{self.customer_code} - {self.name}'

    def save(self, *args, **kwargs):
        if not self.customer_code:
            self.customer_code = generate_year_code('customer', 'C')
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse('customers:detail', kwargs={'pk': self.pk})

    @property
    def total_receivable(self):
        return sum((sale.receivable_amount for sale in self.sales.all()), start=0)
