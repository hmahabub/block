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


COST_WIDGETS = {
    'date': forms.DateInput(attrs={'type': 'date'}),
    'notes': forms.Textarea(attrs={'rows': 2}),
}


class _SupplierOptionalMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['supplier'].required = False


class SharedCostForm(_SupplierOptionalMixin, forms.ModelForm):
    """A cost for the whole building; allocated across every flat by saleable area.

    There is deliberately no flat field, so a shared cost can never be attached
    to a single flat by mistake.
    """

    class Meta:
        model = ProjectCost
        widgets = COST_WIDGETS
        fields = [
            'project', 'cost_category', 'supplier', 'date',
            'reference_no', 'description', 'amount', 'notes',
        ]


class DirectCostForm(_SupplierOptionalMixin, forms.ModelForm):
    """A cost that belongs to one flat only; never allocated to other flats.

    The project comes from the chosen flat, so it can't disagree with it.
    """

    class Meta:
        model = ProjectCost
        widgets = COST_WIDGETS
        fields = [
            'flat', 'cost_category', 'supplier', 'date',
            'reference_no', 'description', 'amount', 'notes',
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['flat'].required = True
        self.fields['flat'].help_text = ''
        self.fields['flat'].queryset = self.fields['flat'].queryset.select_related('project')

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.project = instance.flat.project
        if commit:
            instance.save()
        return instance
