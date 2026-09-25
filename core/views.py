from django.contrib.auth.mixins import PermissionRequiredMixin
from django.urls import reverse_lazy
from django.views.generic import UpdateView

from .forms import CompanyProfileForm
from .mixins import UpdateAuditMixin
from .models import CompanyProfile


class CompanySettingsView(PermissionRequiredMixin, UpdateAuditMixin, UpdateView):
    """Edit the single company profile (letterhead, name, address, phone)."""

    model = CompanyProfile
    form_class = CompanyProfileForm
    template_name = 'core/company_settings.html'
    permission_required = 'core.change_companyprofile'
    success_url = reverse_lazy('core:company-settings')

    def get_object(self, queryset=None):
        return CompanyProfile.objects.first() or CompanyProfile.objects.create()
