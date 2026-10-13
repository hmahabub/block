from django import forms

from core.phone import normalize_phone

from .models import Customer


class CustomerForm(forms.ModelForm):
    same_as_present = forms.BooleanField(
        required=False,
        label='Permanent address is the same as present address',
    )

    class Meta:
        model = Customer
        fields = [
            'title', 'name', 'phone', 'whatsapp_no', 'email',
            'identification_no', 'tin', 'date_of_birth', 'nationality', 'occupation',
            'father_name', 'mother_name', 'spouse_name', 'sms_enabled',
            'emergency_contact_name', 'emergency_contact_phone', 'nominee_name', 'nominee_relation',
            'present_address', 'permanent_address',
            'notes',
        ]
        widgets = {
            'date_of_birth': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
            'present_address': forms.Textarea(attrs={'rows': 2}),
            'permanent_address': forms.Textarea(attrs={'rows': 2}),
            'notes': forms.Textarea(attrs={'rows': 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        instance = self.instance
        if instance.pk and instance.present_address and instance.present_address == instance.permanent_address:
            self.fields['same_as_present'].initial = True

    def _clean_phone(self, name):
        return normalize_phone(self.cleaned_data.get(name, ''))

    def clean_phone(self):
        phone = self._clean_phone('phone')
        if Customer.objects.filter(phone=phone).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError('A customer with this phone number already exists.')
        return phone

    def clean_whatsapp_no(self):
        return self._clean_phone('whatsapp_no')

    def clean_emergency_contact_phone(self):
        return self._clean_phone('emergency_contact_phone')

    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data.get('same_as_present'):
            cleaned_data['permanent_address'] = cleaned_data.get('present_address', '')
        return cleaned_data
