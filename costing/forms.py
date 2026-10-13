from django import forms
from django.db.models import Q

from books.models import Account

from .models import CostCategory, Phase, ProjectBudget, ProjectCost


class CostCategoryForm(forms.ModelForm):
    class Meta:
        model = CostCategory
        fields = ['name', 'parent_category', 'phase', 'active']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['parent_category'].queryset = CostCategory.objects.filter(parent_category__isnull=True)
        self.fields['parent_category'].required = False

    def clean(self):
        cleaned = super().clean()
        parent = cleaned.get('parent_category')
        if parent:
            cleaned['phase'] = parent.phase  # a sub-category always follows its parent
        return cleaned


class ProjectBudgetForm(forms.ModelForm):
    class Meta:
        model = ProjectBudget
        fields = ['project', 'cost_category', 'budget_amount', 'notes']
        widgets = {
            'notes': forms.Textarea(attrs={'rows': 2}),
        }


COST_WIDGETS = {
    'date': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
    'notes': forms.Textarea(attrs={'rows': 2}),
}


class _CostFormBase(forms.ModelForm):
    """Common behaviour of both cost forms.

    * the money must say which bank/cash account it was paid from (it feeds the books);
    * the phase follows the category, except for "either" categories (administration) where the
      person entering the cost chooses it;
    * changing a cost that was already confirmed in the books clears the confirmation, so it is
      checked again.
    """

    phase = forms.ChoiceField(
        choices=[('', '---------')] + list(Phase.choices), required=False,
        help_text='Only needed for administrative costs, which can belong to either phase.',
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['supplier'].required = False
        self.fields['account'].required = True
        self.fields['account'].queryset = Account.objects.filter(is_active=True)
        self.fields['cost_category'].queryset = self.category_queryset()
        self.fields['cost_category'].label_from_instance = self.category_label
        if self.instance.pk:
            self.fields['phase'].initial = self.instance.phase

    def category_queryset(self):
        return CostCategory.objects.filter(active=True).select_related('parent_category')

    @staticmethod
    def category_label(category):
        return f'{category} ({category.get_phase_display()})'

    def phase_map(self):
        """{category id: phase} so the page can show the phase choice only for "either" categories."""
        return {category.pk: category.effective_phase for category in self.fields['cost_category'].queryset}

    def clean(self):
        cleaned = super().clean()
        category = cleaned.get('cost_category')
        if category:
            fixed = category.effective_phase
            if fixed in (Phase.PRE, Phase.POST):
                cleaned['phase'] = fixed
            elif not cleaned.get('phase'):
                self.add_error('phase', 'Choose whether this administrative cost is pre- or post-development.')
        return cleaned

    def _really_changed(self):
        """Whether anything that matters changed. The phase only counts for "either" categories, where
        the person chooses it; elsewhere it follows the category and is not part of the form."""
        category = self.cleaned_data.get('cost_category')
        either = category is not None and category.effective_phase == CostCategory.CategoryPhase.EITHER
        return any(name != 'phase' or either for name in self.changed_data)

    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.cleaned_data.get('phase'):
            instance.phase = self.cleaned_data['phase']
        if instance.pk and instance.is_confirmed and self._really_changed():
            instance.confirmed_at = None
            instance.confirmed_by = None
        if commit:
            instance.save()
        return instance


class SharedCostForm(_CostFormBase):
    """A cost for the whole building.

    Pre-development costs are the company's; post-development costs are shared equally by every flat.
    There is deliberately no flat field, so a shared cost can never be attached to one flat by mistake.
    """

    class Meta:
        model = ProjectCost
        widgets = COST_WIDGETS
        fields = [
            'project', 'cost_category', 'phase', 'supplier', 'account', 'date',
            'reference_no', 'description', 'amount', 'notes',
        ]


class DirectCostForm(_CostFormBase):
    """A cost that belongs to one flat only; never shared with other flats.

    It is always a post-development cost, so pre-development categories are not offered. The project
    comes from the chosen flat, so it can't disagree with it.
    """

    class Meta:
        model = ProjectCost
        widgets = COST_WIDGETS
        fields = [
            'flat', 'cost_category', 'supplier', 'account', 'date',
            'reference_no', 'description', 'amount', 'notes',
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        del self.fields['phase']  # a single-flat cost is always post-development
        self.fields['flat'].required = True
        self.fields['flat'].help_text = ''
        self.fields['flat'].queryset = self.fields['flat'].queryset.select_related('project')

    def category_queryset(self):
        return super().category_queryset().exclude(
            Q(phase=CostCategory.CategoryPhase.PRE)
            | Q(parent_category__phase=CostCategory.CategoryPhase.PRE)
        )

    def clean(self):
        return super(_CostFormBase, self).clean()

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.project = instance.flat.project
        instance.phase = Phase.POST
        if commit:
            instance.save()
        return instance

