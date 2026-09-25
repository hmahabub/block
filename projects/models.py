from django.core.validators import MinValueValidator
from django.db import models
from django.urls import reverse

from core.numbering import generate_code


class Project(models.Model):
    class Status(models.TextChoices):
        PLANNING = 'PLANNING', 'Planning'
        ONGOING = 'ONGOING', 'Ongoing'
        COMPLETED = 'COMPLETED', 'Completed'
        ON_HOLD = 'ON_HOLD', 'On Hold'

    project_code = models.CharField(max_length=20, unique=True, editable=False)
    project_name = models.CharField(max_length=150)
    location = models.CharField(max_length=255, blank=True)
    start_date = models.DateField(null=True, blank=True)
    expected_completion_date = models.DateField(null=True, blank=True)
    floor_no = models.PositiveIntegerField('Number of Floors', default=0)
    land_area = models.DecimalField('Land Area (sqft)', max_digits=12, decimal_places=2, default=0)
    total_saleable_area = models.DecimalField('Total Saleable Area (sqft)', max_digits=12, decimal_places=2, default=0)
    budget_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0, validators=[MinValueValidator(0)])
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PLANNING)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['project_code']),
            models.Index(fields=['status']),
        ]

    def __str__(self):
        return f'{self.project_code} - {self.project_name}'

    def save(self, *args, **kwargs):
        if not self.project_code:
            self.project_code = generate_code('project', 'P')
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse('projects:detail', kwargs={'pk': self.pk})

    @property
    def flat_count(self):
        return self.flats.count()

    @property
    def sold_flat_count(self):
        return self.flats.filter(status=Flat.Status.SOLD).count()

    @property
    def available_flat_count(self):
        return self.flats.filter(status=Flat.Status.AVAILABLE).count()

    @property
    def booked_flat_count(self):
        return self.flats.filter(status=Flat.Status.BOOKED).count()

    @property
    def total_cost(self):
        return self.costs.aggregate(total=models.Sum('amount'))['total'] or 0

    @property
    def total_sales_value(self):
        return self.sales.aggregate(total=models.Sum('net_sale_value'))['total'] or 0

    @property
    def total_received(self):
        return self.sales.aggregate(total=models.Sum('received_amount'))['total'] or 0

    @property
    def total_receivable(self):
        return self.sales.aggregate(total=models.Sum('receivable_amount'))['total'] or 0

    @property
    def estimated_profit(self):
        return self.total_sales_value - self.total_cost

    @property
    def cost_per_sqft(self):
        if self.total_saleable_area:
            return self.total_cost / self.total_saleable_area
        return 0


class Flat(models.Model):
    class Status(models.TextChoices):
        AVAILABLE = 'AVAILABLE', 'Available'
        BOOKED = 'BOOKED', 'Booked'
        SOLD = 'SOLD', 'Sold'

    class FlatType(models.TextChoices):
        STUDIO = 'STUDIO', 'Studio'
        ONE_BED = '1BED', '1 Bedroom'
        TWO_BED = '2BED', '2 Bedroom'
        THREE_BED = '3BED', '3 Bedroom'
        FOUR_BED = '4BED', '4 Bedroom'
        DUPLEX = 'DUPLEX', 'Duplex'
        PENTHOUSE = 'PENTHOUSE', 'Penthouse'
        COMMERCIAL = 'COMMERCIAL', 'Commercial'
        OTHER = 'OTHER', 'Other'

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='flats')
    flat_no = models.CharField(max_length=30)
    floor_no = models.IntegerField()
    flat_type = models.CharField(max_length=20, choices=FlatType.choices, default=FlatType.TWO_BED)
    facing = models.CharField(max_length=50, blank=True)
    bedrooms = models.PositiveSmallIntegerField(null=True, blank=True)
    bathrooms = models.PositiveSmallIntegerField(null=True, blank=True)
    parking_area = models.DecimalField('Parking area (sqft)', max_digits=8, decimal_places=2, null=True, blank=True)
    features = models.CharField('Rooms & features', max_length=255, blank=True,
                                help_text='e.g. Drawing, Dining, Balcony')
    saleable_area = models.DecimalField('Saleable Area (sqft)', max_digits=10, decimal_places=2)
    base_price = models.DecimalField(max_digits=14, decimal_places=2, validators=[MinValueValidator(0)])
    # Managed by FlatSale: Available (no active sale), Booked (active sale not fully
    # paid), Sold (active sale fully paid). Never edited by hand.
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.AVAILABLE, editable=False)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['project', 'floor_no', 'flat_no']
        unique_together = ('project', 'flat_no')
        indexes = [
            models.Index(fields=['status']),
        ]

    def __str__(self):
        return f'{self.project.project_code} / {self.flat_no}'

    def get_absolute_url(self):
        return reverse('projects:flat-detail', kwargs={'pk': self.pk})

    @property
    def allocated_cost(self):
        return self.cost_allocations.aggregate(total=models.Sum('allocated_amount'))['total'] or 0

    @property
    def direct_cost(self):
        return self.project_costs.aggregate(total=models.Sum('amount'))['total'] or 0

    @property
    def total_cost(self):
        return self.allocated_cost + self.direct_cost

    @property
    def current_sale(self):
        return self.sales.exclude(status='CANCELLED').order_by('-sale_date').first()

    @property
    def profit(self):
        sale = self.current_sale
        if not sale:
            return None
        return sale.net_sale_value - self.total_cost

    @property
    def profit_margin(self):
        sale = self.current_sale
        if not sale or not sale.net_sale_value:
            return None
        return (self.profit / sale.net_sale_value) * 100
