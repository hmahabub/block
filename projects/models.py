from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, RegexValidator
from django.db import models, transaction
from django.urls import reverse
from django.utils import timezone

from core.numbering import generate_code

ZERO = Decimal('0')


class Project(models.Model):
    """One building. Every flat in it is identical, so the flat type, size and prices are set here once."""

    class Status(models.TextChoices):
        PLANNING = 'PLANNING', 'Planning'
        ONGOING = 'ONGOING', 'Ongoing'
        COMPLETED = 'COMPLETED', 'Completed'
        ON_HOLD = 'ON_HOLD', 'On Hold'

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

    project_code = models.CharField(max_length=20, unique=True, editable=False)
    project_name = models.CharField(max_length=150)
    location = models.CharField(max_length=255, blank=True)
    start_date = models.DateField(null=True, blank=True)
    expected_completion_date = models.DateField(null=True, blank=True)
    floor_no = models.PositiveIntegerField('Number of Floors', default=0)
    land_area = models.DecimalField('Land Area (sqft)', max_digits=12, decimal_places=2, default=0)
    budget_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0, validators=[MinValueValidator(0)])
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PLANNING)
    description = models.TextField(blank=True)

    # Identical for every flat in the building: set once here, never entered per flat or per sale.
    flat_type = models.CharField(max_length=20, choices=FlatType.choices, default=FlatType.TWO_BED)
    flat_area = models.DecimalField('Saleable area per flat (sqft)', max_digits=10, decimal_places=2, default=0)
    bedrooms = models.PositiveSmallIntegerField(null=True, blank=True)
    bathrooms = models.PositiveSmallIntegerField(null=True, blank=True)
    features = models.CharField('Rooms & features', max_length=255, blank=True,
                                help_text='e.g. Drawing, Dining, Balcony')
    base_price = models.DecimalField(
        'Base price per flat', max_digits=14, decimal_places=2, default=0, validators=[MinValueValidator(0)],
        help_text='What the company needs from each flat share. Anything a buyer pays above it is the reference honorarium.',
    )
    quoted_price = models.DecimalField(
        'Quoted price per flat', max_digits=14, decimal_places=2, default=0, validators=[MinValueValidator(0)],
        help_text='The price quoted to buyers; it pre-fills the sale value.',
    )
    parking_price = models.DecimalField(
        'Parking lot price', max_digits=14, decimal_places=2, default=0, validators=[MinValueValidator(0)],
        help_text='Extra price when the buyer takes the parking lot linked to the flat.',
    )
    parking_area = models.DecimalField('Parking lot area (sqft)', max_digits=8, decimal_places=2, null=True, blank=True)

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

    # --- flats -----------------------------------------------------------------
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
    def total_saleable_area(self):
        return self.flat_area * self.flat_count

    # --- costs -----------------------------------------------------------------
    def cost_total(self, phase=None):
        queryset = self.costs.all() if phase is None else self.costs.filter(phase=phase)
        return queryset.aggregate(total=models.Sum('amount'))['total'] or ZERO

    @property
    def total_cost(self):
        return self.cost_total()

    @property
    def pre_development_cost(self):
        return self.cost_total('PRE')

    @property
    def post_development_cost(self):
        return self.cost_total('POST')

    @property
    def shared_post_cost(self):
        """Post-development costs of the whole building, borne equally by every flat."""
        return self.costs.filter(phase='POST', flat__isnull=True).aggregate(total=models.Sum('amount'))['total'] or ZERO

    @property
    def cost_per_flat(self):
        count = self.flat_count
        return self.shared_post_cost / count if count else ZERO

    @property
    def cost_per_sqft(self):
        area = self.total_saleable_area
        return self.total_cost / area if area else ZERO

    # --- sales -----------------------------------------------------------------
    def _active_sales(self):
        return self.sales.exclude(status='CANCELLED')

    def _sales_sum(self, field):
        return self._active_sales().aggregate(total=models.Sum(field))['total'] or ZERO

    @property
    def total_sales_value(self):
        return self._sales_sum('sale_value')

    @property
    def total_base_value(self):
        """What the company earns from share sales: sale value minus honorarium."""
        return sum((sale.total_base_price for sale in self._active_sales()), ZERO)

    @property
    def total_received(self):
        return self._sales_sum('received_amount')

    @property
    def total_receivable(self):
        return self._sales_sum('receivable_amount')

    @property
    def pre_development_profit(self):
        """Share sales against land, marketing and pre-development administrative cost."""
        return self.total_base_value - self.pre_development_cost


unit_validator = RegexValidator(r'^[A-Z]$', 'Use a single capital letter, for example A.')


class Flat(models.Model):
    """A flat, numbered like A1: the letter is the flat unit and the number is the floor."""

    class Status(models.TextChoices):
        AVAILABLE = 'AVAILABLE', 'Available'
        BOOKED = 'BOOKED', 'Booked'
        SOLD = 'SOLD', 'Sold'

    project = models.ForeignKey(Project, on_delete=models.PROTECT, related_name='flats')
    unit = models.CharField(max_length=1, blank=True, validators=[unit_validator], help_text='Flat unit letter, e.g. A')
    floor_no = models.PositiveSmallIntegerField()
    flat_no = models.CharField(max_length=30, editable=False)
    facing = models.CharField(max_length=50, blank=True)
    parking_lot = models.CharField(
        max_length=20, blank=True, help_text='Parking lot linked to this flat. Defaults to P-<flat no.>.',
    )
    # Managed by FlatSale: Available (no active sale), Booked (active sale not yet fully paid),
    # Sold (sale value fully paid). Never edited by hand.
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.AVAILABLE, editable=False)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['project', 'floor_no', 'unit', 'flat_no']
        unique_together = ('project', 'flat_no')
        indexes = [
            models.Index(fields=['status']),
        ]
        permissions = [('approve_flat_deletion', 'Can approve flat deletion requests')]

    def __str__(self):
        return f'{self.project.project_code} / {self.flat_no}'

    def get_absolute_url(self):
        return reverse('projects:flat-detail', kwargs={'pk': self.pk})

    def save(self, *args, **kwargs):
        # Flats numbered the new way always read unit + floor. Legacy numbers (no unit) are left alone.
        if self.unit:
            self.unit = self.unit.upper()
            self.flat_no = f'{self.unit}{self.floor_no}'
        if not self.parking_lot and self.flat_no:
            self.parking_lot = f'P-{self.flat_no}'[:20]
        super().save(*args, **kwargs)

    # --- specification: identical for every flat, so it lives on the project ---
    @property
    def flat_type(self):
        return self.project.flat_type

    def get_flat_type_display(self):
        return self.project.get_flat_type_display()

    @property
    def saleable_area(self):
        return self.project.flat_area

    @property
    def base_price(self):
        return self.project.base_price

    @property
    def quoted_price(self):
        return self.project.quoted_price

    @property
    def parking_price(self):
        return self.project.parking_price

    @property
    def parking_area(self):
        return self.project.parking_area

    @property
    def bedrooms(self):
        return self.project.bedrooms

    @property
    def bathrooms(self):
        return self.project.bathrooms

    @property
    def features(self):
        return self.project.features

    # --- cost ------------------------------------------------------------------
    @property
    def shared_cost_share(self):
        """This flat's equal share of the building's post-development costs (sold or not)."""
        return self.project.cost_per_flat

    @property
    def direct_cost(self):
        return self.project_costs.aggregate(total=models.Sum('amount'))['total'] or ZERO

    @property
    def total_cost(self):
        return self.shared_cost_share + self.direct_cost

    # --- sale ------------------------------------------------------------------
    @property
    def current_sale(self):
        return self.sales.exclude(status='CANCELLED').order_by('-sale_date', '-id').first()

    # --- deletion --------------------------------------------------------------
    def deletion_blockers(self):
        """Reasons the flat can never be removed (a record would be lost or silently changed)."""
        blockers = []
        if self.sales.exists():
            blockers.append('it has sale records')
        if self.project_costs.exists():
            blockers.append('it has direct cost entries')
        return blockers


class FlatDeletionRequest(models.Model):
    """Deleting a flat needs two different admins: one requests, another approves."""

    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Waiting for a second admin'
        APPROVED = 'APPROVED', 'Approved and deleted'
        REJECTED = 'REJECTED', 'Rejected'
        CANCELLED = 'CANCELLED', 'Withdrawn'

    flat = models.ForeignKey(Flat, null=True, blank=True, on_delete=models.SET_NULL, related_name='deletion_requests')
    flat_label = models.CharField(max_length=120)
    reason = models.TextField(blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+',
    )
    requested_at = models.DateTimeField(auto_now_add=True)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+',
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_note = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ['-requested_at']

    def __str__(self):
        return f'Delete {self.flat_label} ({self.get_status_display()})'

    @staticmethod
    def user_is_admin(user):
        return bool(user and user.is_active and (user.is_superuser or user.has_perm('projects.delete_flat')))

    @classmethod
    def open_for(cls, flat, user, reason=''):
        if not cls.user_is_admin(user):
            raise ValidationError('Only an admin can request a flat deletion.')
        if flat.deletion_blockers():
            raise ValidationError(f'{flat} cannot be deleted: {" and ".join(flat.deletion_blockers())}.')
        if cls.objects.filter(flat=flat, status=cls.Status.PENDING).exists():
            raise ValidationError('A deletion request for this flat is already waiting for approval.')
        return cls.objects.create(flat=flat, flat_label=str(flat), reason=reason, requested_by=user)

    def _require_pending(self):
        if self.status != self.Status.PENDING:
            raise ValidationError('This request has already been dealt with.')

    def _close(self, status, user, note=''):
        self.status, self.decided_by, self.decided_at, self.decision_note = status, user, timezone.now(), note
        self.save()

    @transaction.atomic
    def approve(self, user):
        self._require_pending()
        if not self.user_is_admin(user):
            raise ValidationError('Only an admin can approve a flat deletion.')
        if user.pk == self.requested_by_id:
            raise ValidationError('A second admin must approve; you cannot approve your own request.')
        flat = self.flat
        if flat is None:
            raise ValidationError('The flat no longer exists.')
        if flat.deletion_blockers():
            raise ValidationError(f'{flat} can no longer be deleted: {" and ".join(flat.deletion_blockers())}.')
        flat._deletion_approved = True
        flat.delete()
        self.flat = None
        self._close(self.Status.APPROVED, user)

    def reject(self, user, note=''):
        self._require_pending()
        if not self.user_is_admin(user):
            raise ValidationError('Only an admin can reject a flat deletion.')
        self._close(self.Status.REJECTED, user, note)

    def withdraw(self, user):
        self._require_pending()
        if user.pk != self.requested_by_id:
            raise ValidationError('Only the person who made the request can withdraw it.')
        self._close(self.Status.CANCELLED, user)
