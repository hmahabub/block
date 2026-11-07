from django import forms
from django.db.models import Q
from django.utils import timezone

from books.models import Account

from .models import CostCategory, CostPayment, Phase, ProjectBudget, ProjectCost


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
        labels = {'project': 'Building'}
        widgets = {
            'notes': forms.Textarea(attrs={'rows': 2}),
        }


COST_WIDGETS = {
    'date': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
    'notes': forms.Textarea(attrs={'rows': 2}),
}


class _CostFormBase(forms.ModelForm):
    """Common behaviour of both cost forms.

    * a cost is a voucher: what is owed. The money is paid under the voucher afterwards, from a bank or cash account;
    * the phase follows the category, except for "either" categories (administration) where the
      person entering the cost chooses it;
    * a cost that has been confirmed in the books is part of the book and can no longer be changed.
    """

    phase = forms.ChoiceField(
        choices=[('', '---------')] + list(Phase.choices), required=False,
        help_text='Only needed for administrative costs, which can belong to either phase.',
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if 'project' in self.fields:
            self.fields['project'].label = 'Building'
        self.fields['supplier'].required = False
        self.fields['paid_to'].label = 'Paid to (if not a listed supplier)'
        self.fields['paid_to'].help_text = 'No supplier chosen? Type who the payment was given to.'
        self.fields['cost_category'].queryset = self.category_queryset()
        self.fields['cost_category'].label_from_instance = self.category_label
        if self.instance.pk:
            self.fields['phase'].initial = self.instance.phase

    def check_payee(self, cleaned):
        """Every cost says who was paid: a supplier, or a name typed in."""
        if cleaned.get('supplier'):
            cleaned['paid_to'] = ''          # the supplier is the payee: one source of truth
        elif not (cleaned.get('paid_to') or '').strip():
            # A new cost must say who was paid. An older cost that never had a payee can still be edited as it is.
            if not self.instance.pk or self.instance.payee:
                self.add_error('paid_to', 'Choose a supplier, or type who the payment was given to.')
        else:
            cleaned['paid_to'] = cleaned['paid_to'].strip()

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
        if self.instance.pk and self.instance.is_confirmed:
            raise forms.ValidationError('This cost has a payment confirmed in the books and can no longer be changed.')
        amount = cleaned.get('amount')
        if self.instance.pk and amount is not None and amount < self.instance.paid_amount:
            self.add_error('amount', f'{self.instance.paid_amount:,.2f} has already been paid under this voucher: the amount cannot be less.')
        self.check_payee(cleaned)
        category = cleaned.get('cost_category')
        if category:
            fixed = category.effective_phase
            if fixed in (Phase.PRE, Phase.POST):
                cleaned['phase'] = fixed
            elif not cleaned.get('phase'):
                self.add_error('phase', 'Choose whether this administrative cost is pre- or post-development.')
        return cleaned

    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.cleaned_data.get('phase'):
            instance.phase = self.cleaned_data['phase']
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
            'project', 'cost_category', 'phase', 'supplier', 'paid_to', 'date',
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
            'flat', 'cost_category', 'supplier', 'paid_to', 'date',
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
        cleaned = super(_CostFormBase, self).clean()
        self.check_payee(cleaned)
        return cleaned

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.project = instance.flat.project
        instance.phase = Phase.POST
        if commit:
            instance.save()
        return instance



class CostPaymentForm(forms.ModelForm):
    """A payment made under a cost voucher: no more than what is still due on it."""

    class Meta:
        model = CostPayment
        fields = ['date', 'amount', 'account', 'reference_no', 'notes']
        widgets = {'date': COST_WIDGETS.get('date', forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d')), 'notes': forms.TextInput()}

    def __init__(self, *args, cost=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.cost = cost
        self.fields['account'].queryset = Account.objects.filter(is_active=True)
        self.fields['date'].initial = timezone.localdate()
        self.fields['amount'].initial = cost.due_amount if cost else None

    def clean_amount(self):
        amount = self.cleaned_data['amount']
        due = self.cost.due_amount
        if due <= 0:
            raise forms.ValidationError('This voucher is already paid in full.')
        if amount > due:
            raise forms.ValidationError(f'Only {due:,.2f} is still due on {self.cost.voucher_no}.')
        return amount

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.cost = self.cost
        if commit:
            instance.save()
        return instance
