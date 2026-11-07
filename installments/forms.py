import datetime
from decimal import Decimal

from django import forms
from django.utils import timezone

from projects.models import Project

from .models import Installment

DATE_WIDGET = forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d')


class IssueInstallmentForm(forms.ModelForm):
    """Issue an installment: every customer who booked a flat in the project is charged and told the deadline."""

    send_sms = forms.BooleanField(
        required=False, initial=True, label='Send each customer an SMS with the amount and the deadline',
    )

    class Meta:
        model = Installment
        fields = ['title', 'due_date', 'basis', 'value', 'building', 'notes']
        widgets = {'due_date': DATE_WIDGET, 'notes': forms.Textarea(attrs={'rows': 2})}

    def __init__(self, *args, development=None, number=1, **kwargs):
        super().__init__(*args, **kwargs)
        self.development = development
        self.fields['building'].queryset = Project.objects.filter(development=development)
        self.fields['building'].empty_label = 'Every building of the project'
        self.fields['title'].initial = f'Installment {number}'
        self.fields['due_date'].initial = timezone.localdate() + datetime.timedelta(days=15)

    def clean_due_date(self):
        due = self.cleaned_data['due_date']
        if due < timezone.localdate():
            raise forms.ValidationError('The payment deadline cannot be in the past.')
        return due

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('basis') == Installment.Basis.PERCENT and cleaned.get('value') is not None and cleaned['value'] > Decimal(100):
            self.add_error('value', 'A percentage cannot be more than 100.')
        return cleaned
