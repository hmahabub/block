from django import forms
from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils import timezone

from .models import CostCategory, CostPayment, ProjectBudget, ProjectCost


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


class CostPaymentForm(forms.ModelForm):
    """Records a payment against one specific cost; can't exceed what is still payable."""

    class Meta:
        model = CostPayment
        fields = ['payment_date', 'amount', 'payment_method', 'reference_no', 'notes']
        widgets = {
            'payment_date': forms.DateInput(attrs={'type': 'date'}),
            'notes': forms.Textarea(attrs={'rows': 2}),
        }

    def __init__(self, *args, project_cost, **kwargs):
        super().__init__(*args, **kwargs)
        self.project_cost = project_cost
        self.instance.project_cost = project_cost
        if not self.instance.pk:
            self.fields['payment_date'].initial = timezone.now().date()
            self.fields['amount'].initial = project_cost.payable_amount

    def clean_amount(self):
        amount = self.cleaned_data['amount']
        remaining = self.project_cost.payable_amount
        if amount > remaining:
            symbol = settings.CURRENCY_SYMBOL
            raise ValidationError(
                f'This payment of {symbol}{amount} exceeds the remaining payable amount of {symbol}{remaining}.'
            )
        return amount
