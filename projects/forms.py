from django import forms

from .models import Flat, Project


class ProjectForm(forms.ModelForm):
    class Meta:
        model = Project
        fields = [
            'project_name', 'location', 'status', 'start_date', 'expected_completion_date',
            'floor_no', 'land_area', 'budget_amount', 'description',
            'flat_type', 'flat_area', 'bedrooms', 'bathrooms', 'features',
            'base_price', 'quoted_price', 'parking_price', 'parking_area',
        ]
        widgets = {
            'start_date': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
            'expected_completion_date': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
            'description': forms.Textarea(attrs={'rows': 2}),
        }

    def clean(self):
        cleaned = super().clean()
        base, quoted = cleaned.get('base_price'), cleaned.get('quoted_price')
        if base is not None and quoted is not None and quoted < base:
            self.add_error('quoted_price', 'The quoted price cannot be below the base price.')
        return cleaned


class FlatForm(forms.ModelForm):
    unit = forms.CharField(
        max_length=1, label='Unit letter',
        help_text='Flat number = unit letter + floor, e.g. unit A on floor 3 is A3.',
    )

    class Meta:
        model = Flat
        fields = ['unit', 'floor_no', 'facing', 'parking_lot', 'notes']
        widgets = {'notes': forms.Textarea(attrs={'rows': 2})}

    def __init__(self, *args, project=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.project = project or self.instance.project

    def clean_unit(self):
        unit = self.cleaned_data['unit'].strip().upper()
        if not unit.isalpha() or len(unit) != 1:
            raise forms.ValidationError('Use a single letter, for example A.')
        return unit

    def clean(self):
        cleaned = super().clean()
        unit, floor = cleaned.get('unit'), cleaned.get('floor_no')
        if unit and floor is not None:
            flat_no = f'{unit}{floor}'
            clash = Flat.objects.filter(project=self.project, flat_no=flat_no).exclude(pk=self.instance.pk)
            if clash.exists():
                raise forms.ValidationError(f'Flat {flat_no} already exists in this project.')
        return cleaned


class GenerateFlatsForm(forms.Form):
    floors = forms.IntegerField(min_value=1, max_value=200, label='Number of floors')
    units_per_floor = forms.IntegerField(min_value=1, max_value=26, label='Flat units per floor',
                                         help_text='4 units gives A, B, C and D on every floor.')

    def __init__(self, *args, project=None, **kwargs):
        super().__init__(*args, **kwargs)
        if project is not None and not self.is_bound:
            self.fields['floors'].initial = project.floor_no or 1


class FlatDeletionRequestForm(forms.Form):
    reason = forms.CharField(
        widget=forms.Textarea(attrs={'rows': 3}), required=True,
        help_text='Why should this flat be removed? Another admin has to approve it.',
    )


class DecisionNoteForm(forms.Form):
    note = forms.CharField(max_length=300, required=False, label='Note (optional)')
