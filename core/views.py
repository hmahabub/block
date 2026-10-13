from django.conf import settings
from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.shortcuts import redirect
from django.urls import reverse, reverse_lazy
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST
from django.views.generic import FormView, UpdateView

from . import reauth
from .sessions import end_all_sessions
from .forms import CompanyProfileForm, ConfirmPasswordForm
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


class ConfirmPasswordView(LoginRequiredMixin, FormView):
    """Ask for the login password again before opening a sensitive screen."""

    template_name = 'core/confirm_password.html'
    form_class = ConfirmPasswordForm
    max_failures = 5
    failures_key = 'reauth_failures'

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def get_next_url(self):
        url = self.request.POST.get('next') or self.request.GET.get('next') or ''
        if url and url_has_allowed_host_and_scheme(
            url, allowed_hosts={self.request.get_host()}, require_https=self.request.is_secure()
        ):
            return url
        return reverse('home')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['next'] = self.get_next_url()
        context['window_minutes'] = settings.REAUTH_MINUTES
        return context

    def form_valid(self, form):
        self.request.session.pop(self.failures_key, None)
        reauth.unlock(self.request)
        return redirect(self.get_next_url())

    def form_invalid(self, form):
        failures = self.request.session.get(self.failures_key, 0) + 1
        if failures >= self.max_failures:
            logout(self.request)
            messages.error(self.request, 'Too many wrong passwords. You have been signed out.')
            return redirect('login')
        self.request.session[self.failures_key] = failures
        return super().form_invalid(form)


@login_required
@require_POST
def logout_everywhere(request):
    """Sign this user out on every device, including this one."""
    end_all_sessions(request.user)
    logout(request)  # clears the current request's session cookie as well
    messages.info(request, 'You have been signed out on all devices.')
    return redirect('login')


@login_required
@require_POST
def lock_screens(request):
    reauth.lock(request)
    messages.info(request, 'Sensitive screens are locked. You will be asked for your password to open them again.')
    return redirect('home')
