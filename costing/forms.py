from django import forms

from .models import CostCategory, ProjectBudget, ProjectCost


class CostCategoryForm(forms.ModelForm):
    class Meta:
        model = CostCategory
        fields = ['name', 'parent_category', 'active']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['parent_category'].queryset = CostCategory.objects.filter(parent_category__isnull=True)
        self.fields['parent_category'].required = False


class ProjectBudgetForm(forms.ModelForm):
    class Meta:
        model = ProjectBudget
        fields = ['project', 'cost_category', 'budget_amount', 'notes']
        widgets = {
            'notes': forms.Textarea(attrs={'rows': 2}),
        }


class ProjectCostForm(forms.ModelForm):
    class Meta:
        model = ProjectCost
        fields = [
            'project', 'cost_category', 'supplier', 'flat', 'date',
            'reference_no', 'description', 'amount', 'notes',
        ]
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date'}),
            'notes': forms.Textarea(attrs={'rows': 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['flat'].required = False
        self.fields['supplier'].required = False
