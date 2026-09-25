from django.core.validators import RegexValidator
from django.db import models
from django.urls import reverse

phone_regex = RegexValidator(
    regex=r'^\+?1?\d{9,15}$',
    message="Phone number must be in format: '+999999999'. Up to 15 digits allowed.",
)


class Customer(models.Model):
    name = models.CharField('Customer Name', max_length=150)
    phone = models.CharField(validators=[phone_regex], max_length=17, unique=True)
    email = models.EmailField(blank=True)
    identification_no = models.CharField('NID / Passport No.', max_length=50, blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    nationality = models.CharField(max_length=50, default='Bangladeshi', blank=True)
    occupation = models.CharField('Occupation / Profession', max_length=100, blank=True)

    father_name = models.CharField("Father's name", max_length=150, blank=True)
    mother_name = models.CharField("Mother's name", max_length=150, blank=True)
    spouse_name = models.CharField("Spouse's name", max_length=150, blank=True)

    present_address = models.TextField(blank=True)
    permanent_address = models.TextField(blank=True)

    nominee_name = models.CharField('Nominee name', max_length=150, blank=True)
    nominee_relation = models.CharField('Nominee relation', max_length=50, blank=True)

    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        indexes = [
            models.Index(fields=['name']),
        ]

    def __str__(self):
        return f'{self.name} ({self.phone})'

    def get_absolute_url(self):
        return reverse('customers:detail', kwargs={'pk': self.pk})

    @property
    def total_receivable(self):
        return sum((sale.receivable_amount for sale in self.sales.all()), start=0)
