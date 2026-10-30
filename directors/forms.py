from django import forms
from django.core.validators import RegexValidator
from django.utils import timezone

from books.models import Account
from core.phone import normalize_phone
from projects.models import Development

from .models import Director, DirectorTransaction

phone_regex = RegexValidator(regex=r'^\+?\d{9,15}$', message='Phone number must be like +8801711000000 or 01711000000.')


class DirectorForm(forms.ModelForm):
    class Meta:
        model = Director
        fields = ['name', 'phone', 'email', 'identification_no', 'address', 'is_active', 'notes']
        widgets = {'address': forms.Textarea(attrs={'rows': 2}), 'notes': forms.Textarea(attrs={'rows': 2})}

    def clean_phone(self):
        phone = normalize_phone((self.cleaned_data.get('phone') or '').strip())
        if phone:
            phone_regex(phone)
        return phone

    def clean_identification_no(self):
        value = (self.cleaned_data.get('identification_no') or '').strip()
        if value:
            clash = Director.objects.filter(identification_no__iexact=value).exclude(pk=self.instance.pk).first()
            if clash:
                raise forms.ValidationError(f'NID / passport {value} already belongs to director {clash.name}.')
        return value


class DirectorTransactionForm(forms.ModelForm):
    class Meta:
        model = DirectorTransaction
        fields = ['director', 'development', 'kind', 'date', 'amount', 'account', 'reference_note', 'notes']
        widgets = {'date': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d')}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['director'].queryset = Director.objects.filter(is_active=True) | Director.objects.filter(
            pk=self.instance.director_id or 0)
        self.fields['development'].queryset = Development.objects.all()
        self.fields['account'].queryset = Account.objects.filter(is_active=True)
        self.fields['kind'].help_text = (
            'Investment: money the director puts in. Capital withdrawal: investment paid back. '
            'Profit share paid: profit given on top of the capital.'
        )
        if not self.instance.pk:
            self.fields['date'].initial = timezone.localdate()
