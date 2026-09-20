from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Sum
from django.urls import reverse
from django.utils.text import slugify


class CostCategory(models.Model):
    name = models.CharField(max_length=100)
    parent_category = models.ForeignKey(
        'self', null=True, blank=True, on_delete=models.CASCADE, related_name='subcategories'
    )
    code = models.SlugField(max_length=60, unique=True, blank=True)
    active = models.BooleanField(default=True)

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
        super().save(*args, **kwargs)

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


class ProjectCost(models.Model):
    class Status(models.TextChoices):
        UNPAID = 'UNPAID', 'Unpaid'
        PARTIAL = 'PARTIAL', 'Partially Paid'
        PAID = 'PAID', 'Paid'

    project = models.ForeignKey('projects.Project', on_delete=models.CASCADE, related_name='costs')
    cost_category = models.ForeignKey(CostCategory, on_delete=models.PROTECT, related_name='project_costs')
    supplier = models.ForeignKey(
        'suppliers.Supplier', null=True, blank=True, on_delete=models.SET_NULL, related_name='project_costs'
    )
    apartment = models.ForeignKey(
        'projects.Apartment', null=True, blank=True, on_delete=models.SET_NULL, related_name='project_costs',
        help_text='Leave blank for a shared project cost — it will be allocated across every '
                   'apartment in the project by saleable area. Set it for a cost that belongs to one apartment only.',
    )
    date = models.DateField()
    reference_no = models.CharField('Reference / Bill No.', max_length=100, blank=True)
    description = models.CharField(max_length=255, blank=True)
    amount = models.DecimalField(max_digits=14, decimal_places=2, validators=[MinValueValidator(0.01)])
    paid_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0, editable=False)
    payable_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0, editable=False)
    allocation_required = models.BooleanField(default=True, editable=False)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.UNPAID, editable=False)
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

    def save(self, *args, **kwargs):
        self.allocation_required = self.apartment_id is None
        self.payable_amount = self.amount - self.paid_amount
        if self.paid_amount <= 0:
            self.status = self.Status.UNPAID
        elif self.paid_amount >= self.amount:
            self.status = self.Status.PAID
        else:
            self.status = self.Status.PARTIAL
        super().save(*args, **kwargs)
        if self.allocation_required:
            self._recompute_allocation()
        else:
            self.cost_allocations.all().delete()

    def _recompute_allocation(self):
        """Area-based allocation: allocated = cost.amount * apartment_area / total_saleable_area."""
        self.cost_allocations.all().delete()
        total_area = self.project.total_saleable_area
        if not total_area:
            return
        allocations = []
        for apartment in self.project.apartments.all():
            rate = apartment.saleable_area / total_area
            allocations.append(CostAllocation(
                project_cost=self,
                project=self.project,
                apartment=apartment,
                apartment_area=apartment.saleable_area,
                project_saleable_area=total_area,
                allocation_rate=rate,
                allocated_amount=self.amount * rate,
            ))
        CostAllocation.objects.bulk_create(allocations)

    def recalc_paid_amount(self):
        total_paid = self.payments.aggregate(total=Sum('amount'))['total'] or 0
        self.paid_amount = total_paid
        self.save()


class CostAllocation(models.Model):
    project_cost = models.ForeignKey(ProjectCost, on_delete=models.CASCADE, related_name='cost_allocations')
    project = models.ForeignKey('projects.Project', on_delete=models.CASCADE, related_name='cost_allocations')
    apartment = models.ForeignKey('projects.Apartment', on_delete=models.CASCADE, related_name='cost_allocations')
    apartment_area = models.DecimalField(max_digits=10, decimal_places=2)
    project_saleable_area = models.DecimalField(max_digits=12, decimal_places=2)
    allocation_rate = models.DecimalField(max_digits=12, decimal_places=8)
    allocated_amount = models.DecimalField(max_digits=14, decimal_places=2)

    class Meta:
        ordering = ['apartment__floor_no', 'apartment__apartment_no']

    def __str__(self):
        return f'{self.apartment} <- {self.project_cost} : {self.allocated_amount}'
