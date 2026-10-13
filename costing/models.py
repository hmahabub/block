from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Sum
from django.urls import reverse
from django.utils.text import slugify

from core.models import ConfirmableModel


class Phase(models.TextChoices):
    PRE = 'PRE', 'Pre-development'
    POST = 'POST', 'Post-development'


class CostCategory(models.Model):
    """A cost head. Its phase decides who bears the cost.

    Pre-development (land, marketing): the company, set against the profit on share sales.
    Post-development (everything after construction starts): borne equally by all flat owners.
    Administrative costs can fall in either phase, so the phase is chosen on each cost entry.
    """

    class CategoryPhase(models.TextChoices):
        PRE = 'PRE', 'Pre-development'
        POST = 'POST', 'Post-development'
        EITHER = 'EITHER', 'Either (chosen on each entry)'

    name = models.CharField(max_length=100)
    parent_category = models.ForeignKey(
        'self', null=True, blank=True, on_delete=models.CASCADE, related_name='subcategories'
    )
    code = models.SlugField(max_length=60, unique=True, blank=True)
    active = models.BooleanField(default=True)
    phase = models.CharField(
        max_length=6, choices=CategoryPhase.choices, default=CategoryPhase.POST,
        help_text='Sub-categories always follow their parent category.',
    )

    class Meta:
        ordering = ['parent_category__id', 'name']
        verbose_name = 'Cost Category'
        verbose_name_plural = 'Cost Categories'

    def __str__(self):
        if self.parent_category:
            return f'{self.parent_category.name} / {self.name}'
        return self.name

    def save(self, *args, **kwargs):
        if not self.code:
            base = f'{self.parent_category.code}-{self.name}' if self.parent_category else self.name
            self.code = slugify(base)[:60]
        if self.parent_category_id:
            self.phase = self.parent_category.phase
        super().save(*args, **kwargs)
        if not self.parent_category_id:
            self.subcategories.exclude(phase=self.phase).update(phase=self.phase)

    @property
    def effective_phase(self):
        return self.parent_category.phase if self.parent_category_id else self.phase

    def get_absolute_url(self):
        return reverse('costing:category-list')

    @property
    def is_top_level(self):
        return self.parent_category_id is None


class ProjectBudget(models.Model):
    project = models.ForeignKey('projects.Project', on_delete=models.CASCADE, related_name='budgets')
    cost_category = models.ForeignKey(CostCategory, on_delete=models.PROTECT, related_name='budgets')
    budget_amount = models.DecimalField(max_digits=14, decimal_places=2, validators=[MinValueValidator(0)])
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['project', 'cost_category']
        unique_together = ('project', 'cost_category')

    def __str__(self):
        return f'{self.project.project_code} / {self.cost_category} budget'

    @property
    def actual_cost(self):
        category_ids = [self.cost_category_id] + list(
            self.cost_category.subcategories.values_list('pk', flat=True)
        )
        total = ProjectCost.objects.filter(
            project=self.project, cost_category_id__in=category_ids
        ).aggregate(total=Sum('amount'))['total']
        return total or 0

    @property
    def difference(self):
        return self.budget_amount - self.actual_cost


class ProjectCost(ConfirmableModel):
    project = models.ForeignKey('projects.Project', on_delete=models.CASCADE, related_name='costs')
    cost_category = models.ForeignKey(CostCategory, on_delete=models.PROTECT, related_name='project_costs')
    phase = models.CharField(
        max_length=4, choices=Phase.choices, default=Phase.POST,
        help_text='Pre-development costs offset the share-sale profit; post-development costs are borne equally by all flat owners.',
    )
    supplier = models.ForeignKey(
        'suppliers.Supplier', null=True, blank=True, on_delete=models.SET_NULL, related_name='project_costs'
    )
    flat = models.ForeignKey(
        'projects.Flat', null=True, blank=True, on_delete=models.SET_NULL, related_name='project_costs',
        help_text='Leave blank for a shared project cost, borne equally by every flat in the project. '
                   'Set it only for a cost that belongs to one flat.',
    )
    account = models.ForeignKey(
        'books.Account', null=True, blank=True, on_delete=models.PROTECT, related_name='costs',
        verbose_name='Paid from', help_text='The bank or cash account the money was paid from.',
    )
    date = models.DateField()
    reference_no = models.CharField('Reference / Bill No.', max_length=100, blank=True)
    description = models.CharField(max_length=255, blank=True)
    amount = models.DecimalField(max_digits=14, decimal_places=2, validators=[MinValueValidator(0.01)])
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-date', '-id']
        verbose_name = 'Project Cost'
        verbose_name_plural = 'Project Costs'

    def __str__(self):
        return f'{self.project.project_code} / {self.cost_category} / {self.amount}'

    def get_absolute_url(self):
        return reverse('costing:cost-detail', kwargs={'pk': self.pk})

    @property
    def voucher_no(self):
        return f'CV-{self.pk:05d}'

    @property
    def is_shared(self):
        return self.flat_id is None

    @property
    def share_per_flat(self):
        """Each flat's equal share when this is a shared post-development cost, otherwise None."""
        if not (self.is_shared and self.phase == Phase.POST):
            return None
        count = self.project.flat_count
        return self.amount / count if count else Decimal('0')

    def save(self, *args, **kwargs):
        # The category fixes the phase, except for "either" categories where the entry chooses.
        category_phase = self.cost_category.effective_phase
        if category_phase in (Phase.PRE, Phase.POST):
            self.phase = category_phase
        if self.flat_id:
            self.phase = Phase.POST  # a cost that belongs to one flat is always a flat-owner cost
        super().save(*args, **kwargs)
