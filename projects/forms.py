from django import forms

from .models import Flat, Project


class ProjectForm(forms.ModelForm):
    class Meta:
        model = Project
        fields = [
            'project_name', 'location', 'start_date', 'expected_completion_date',
            'floor_no', 'land_area', 'total_saleable_area', 'budget_amount',
            'status', 'description',
        ]
        widgets = {
            'start_date': forms.DateInput(attrs={'type': 'date'}),
            'expected_completion_date': forms.DateInput(attrs={'type': 'date'}),
            'description': forms.Textarea(attrs={'rows': 3}),
        }


class FlatForm(forms.ModelForm):
    class Meta:
        model = Flat
        fields = ['flat_no', 'floor_no', 'flat_type', 'facing', 'saleable_area', 'base_price', 'status', 'notes']
        widgets = {
            'notes': forms.Textarea(attrs={'rows': 2}),
        }
