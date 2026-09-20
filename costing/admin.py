from django.contrib import admin

from .models import CostAllocation, CostCategory, ProjectBudget, ProjectCost


@admin.register(CostCategory)
class CostCategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'parent_category', 'code', 'active')
    list_filter = ('active', 'parent_category')
    search_fields = ('name', 'code')


@admin.register(ProjectBudget)
class ProjectBudgetAdmin(admin.ModelAdmin):
    list_display = ('project', 'cost_category', 'budget_amount')
    list_filter = ('project',)


@admin.register(ProjectCost)
class ProjectCostAdmin(admin.ModelAdmin):
    list_display = ('project', 'cost_category', 'flat', 'amount', 'paid_amount', 'payable_amount', 'status', 'date')
    list_filter = ('status', 'project', 'cost_category')
    search_fields = ('description', 'reference_no')


@admin.register(CostAllocation)
class CostAllocationAdmin(admin.ModelAdmin):
    list_display = ('project_cost', 'flat', 'allocated_amount')
    list_filter = ('project',)
