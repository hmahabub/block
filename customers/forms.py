from django import forms

from .models import Customer


class CustomerForm(forms.ModelForm):
    same_as_present = forms.BooleanField(
        required=False,
        label='Permanent address is the same as present address',
    )

    class Meta:
        model = Customer
        fields = [
            'name', 'phone', 'email', 'identification_no', 'date_of_birth', 'nationality', 'occupation',
            'father_name', 'mother_name', 'spouse_name',
            'present_address', 'permanent_address',
            'nominee_name', 'nominee_relation',
            'notes',
        ]
        widgets = {
            'date_of_birth': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
            'present_address': forms.Textarea(attrs={'rows': 3}),
            'permanent_address': forms.Textarea(attrs={'rows': 3}),
            'notes': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        instance = self.instance
        if instance.pk and instance.present_address and instance.present_address == instance.permanent_address:
            self.fields['same_as_present'].initial = True

    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data.get('same_as_present'):
            cleaned_data['permanent_address'] = cleaned_data.get('present_address', '')
        return cleaned_data
