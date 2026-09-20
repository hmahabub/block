from django.core.validators import MinValueValidator
from django.db import models
from django.urls import reverse

from core.numbering import generate_slash_code


class ApartmentSale(models.Model):
    class Status(models.TextChoices):
        BOOKED = 'BOOKED', 'Booked'
        SOLD = 'SOLD', 'Sold'
        CANCELLED = 'CANCELLED', 'Cancelled'

    sale_no = models.CharField(max_length=30, unique=True, editable=False)
    project = models.ForeignKey('projects.Project', on_delete=models.CASCADE, related_name='sales')
    apartment = models.ForeignKey('projects.Apartment', on_delete=models.CASCADE, related_name='sales')
    customer = models.ForeignKey('customers.Customer', on_delete=models.PROTECT, related_name='sales')
    sale_date = models.DateField()
    base_price = models.DecimalField(max_digits=14, decimal_places=2, validators=[MinValueValidator(0)])
    other_charges = models.DecimalField('Parking / Other Charges', max_digits=14, decimal_places=2, default=0)
    discount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    net_sale_value = models.DecimalField(max_digits=14, decimal_places=2, default=0, editable=False)
    received_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0, editable=False)
    receivable_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0, editable=False)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.BOOKED)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-sale_date', '-id']
        verbose_name = 'Apartment Sale'

    def __str__(self):
        return f'{self.sale_no} - {self.apartment}'

    def get_absolute_url(self):
        return reverse('sales:detail', kwargs={'pk': self.pk})

    def save(self, *args, **kwargs):
        if not self.sale_no:
            self.sale_no = generate_slash_code('sale')
        if not self.project_id and self.apartment_id:
            self.project = self.apartment.project
        self.net_sale_value = self.base_price + self.other_charges - self.discount
        self.receivable_amount = self.net_sale_value - self.received_amount
        super().save(*args, **kwargs)
        self._sync_apartment_status()

    def _sync_apartment_status(self):
        from projects.models import Apartment

        apartment = self.apartment
        if self.status == self.Status.CANCELLED:
            if not apartment.sales.exclude(pk=self.pk).exclude(status=self.Status.CANCELLED).exists():
                apartment.status = Apartment.Status.AVAILABLE
                apartment.save(update_fields=['status'])
        elif self.status in (self.Status.BOOKED, self.Status.SOLD):
            apartment.status = Apartment.Status.BOOKED if self.status == self.Status.BOOKED else Apartment.Status.SOLD
            apartment.save(update_fields=['status'])

    def recalc_received_amount(self):
        total = self.payments.aggregate(total=models.Sum('amount'))['total'] or 0
        self.received_amount = total
        self.save()


class CustomerPayment(models.Model):
    class Method(models.TextChoices):
        CASH = 'CASH', 'Cash'
        BANK = 'BANK', 'Bank'
        CHEQUE = 'CHEQUE', 'Cheque'
        OTHER = 'OTHER', 'Other'

    sale = models.ForeignKey(ApartmentSale, on_delete=models.CASCADE, related_name='payments')
    customer = models.ForeignKey('customers.Customer', on_delete=models.PROTECT, related_name='payments')
    payment_date = models.DateField()
    amount = models.DecimalField(max_digits=14, decimal_places=2, validators=[MinValueValidator(0.01)])
    payment_method = models.CharField(max_length=10, choices=Method.choices, default=Method.BANK)
    reference_no = models.CharField(max_length=100, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-payment_date', '-id']
        verbose_name = 'Customer Payment'

    def __str__(self):
        return f'{self.customer} - {self.amount} ({self.payment_date})'

    def save(self, *args, **kwargs):
        if not self.customer_id and self.sale_id:
            self.customer = self.sale.customer
        super().save(*args, **kwargs)
        self.sale.recalc_received_amount()

    def delete(self, *args, **kwargs):
        sale = self.sale
        super().delete(*args, **kwargs)
        sale.recalc_received_amount()
