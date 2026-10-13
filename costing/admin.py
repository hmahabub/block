from django.contrib import admin

from .models import CostCategory, ProjectBudget, ProjectCost


@admin.register(CostCategory)
class CostCategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'parent_category', 'phase', 'code', 'active')
    list_filter = ('active', 'phase', 'parent_category')
    search_fields = ('name', 'code')


@admin.register(ProjectBudget)
class ProjectBudgetAdmin(admin.ModelAdmin):
    list_display = ('project', 'cost_category', 'budget_amount')
    list_filter = ('project',)


@admin.register(ProjectCost)
class ProjectCostAdmin(admin.ModelAdmin):
    list_display = ('project', 'cost_category', 'phase', 'flat', 'account', 'amount', 'date')
    list_filter = ('project', 'phase', 'cost_category')
    search_fields = ('description', 'reference_no')


