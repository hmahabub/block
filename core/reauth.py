"""Password re-entry ("sudo mode") for sensitive screens.

The software is shown to buyers on the same logins that record money entries, so screens
such as Costing and the books ask the signed-in user to type their password again before
opening. Access then stays unlocked while the user keeps working, and locks again after
`REAUTH_MINUTES` of inactivity on sensitive screens (or when the user presses "Lock").
"""
import time
from urllib.parse import urlencode

from django.conf import settings
from django.shortcuts import redirect
from django.urls import reverse

SESSION_KEY = 'reauth_until'


def is_unlocked(request):
    return request.session.get(SESSION_KEY, 0) > time.time()


def unlock(request):
    request.session[SESSION_KEY] = time.time() + settings.REAUTH_MINUTES * 60


def lock(request):
    request.session.pop(SESSION_KEY, None)


class ReauthMiddleware:
    """Redirect signed-in users to the confirm-password page when opening a sensitive URL namespace."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        match = request.resolver_match
        if not match or not request.user.is_authenticated:
            return None
        namespace = match.namespaces[0] if match.namespaces else ''
        if namespace not in settings.SENSITIVE_NAMESPACES:
            return None
        if is_unlocked(request):
            unlock(request)  # sliding window: stays open while the user is active
            return None
        return redirect(f"{reverse('confirm-password')}?{urlencode({'next': request.get_full_path()})}")
