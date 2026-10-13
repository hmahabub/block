from django import forms

from .models import CompanyProfile

MAX_LETTERHEAD_BYTES = 5 * 1024 * 1024
ALLOWED_FORMATS = ('PNG', 'JPEG')


class CompanyProfileForm(forms.ModelForm):
    class Meta:
        model = CompanyProfile
        fields = ['letterhead', 'name', 'address', 'phone']
        widgets = {'address': forms.Textarea(attrs={'rows': 2})}

    def clean_letterhead(self):
        letterhead = self.cleaned_data.get('letterhead')
        # `False` means the "clear" box was ticked; an existing, unchanged file has no `.image`.
        if letterhead and hasattr(letterhead, 'image'):
            if letterhead.size > MAX_LETTERHEAD_BYTES:
                raise forms.ValidationError('The letterhead image must be 5 MB or smaller.')
            if letterhead.image.format not in ALLOWED_FORMATS:
                raise forms.ValidationError('Please upload a PNG or JPG image.')
        return letterhead

    def save(self, commit=True):
        old_file = CompanyProfile.objects.filter(pk=self.instance.pk).first() if self.instance.pk else None
        old_name = old_file.letterhead.name if old_file and old_file.letterhead else None
        instance = super().save(commit=commit)
        # Don't leave replaced/cleared letterhead files piling up on disk.
        if commit and old_name and old_name != (instance.letterhead.name if instance.letterhead else None):
            old_file.letterhead.storage.delete(old_name)
        return instance


class ConfirmPasswordForm(forms.Form):
    password = forms.CharField(
        label='Your password', widget=forms.PasswordInput(attrs={'autofocus': True, 'autocomplete': 'current-password'}),
    )

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

    def clean_password(self):
        password = self.cleaned_data['password']
        if not self.user.check_password(password):
            raise forms.ValidationError('That password is not correct.')
        return password
