"""Password re-entry ("sudo mode") for sensitive screens.

The software is shown to buyers on the same logins that record money entries, so screens
such as Costing and the books ask the signed-in user to type their password again before
opening. Access then stays unlocked while the user keeps working, and locks again after
`REAUTH_MINUTES` of inactivity on sensitive screens (or when the user presses "Lock").

The unlock is also tied to a cookie with no expiry date, which the browser throws away when it is closed. So
closing the browser locks the sensitive screens again straight away, even though the login itself may last longer.
"""
import secrets
import time
from urllib.parse import urlencode

from django.conf import settings
from django.shortcuts import redirect
from django.urls import reverse

SESSION_KEY = 'reauth_until'
TOKEN_KEY = 'reauth_token'
COOKIE_NAME = 'daj_unlocked'


def is_unlocked(request):
    """Unlocked only while the time window is open AND the browser still has this session's unlock cookie."""
    if request.session.get(SESSION_KEY, 0) <= time.time():
        return False
    token = request.session.get(TOKEN_KEY, '')
    return bool(token) and secrets.compare_digest(token, request.COOKIES.get(COOKIE_NAME, ''))


def money_visible(request):
    """Whether money figures (costs, sale value, received, receivable ...) may be shown on the open screen.

    They are hidden while the sensitive screens are locked, because the software is shown to buyers.
    Nothing is hidden when no screens are configured as sensitive."""
    return not settings.SENSITIVE_NAMESPACES or is_unlocked(request)


def unlock(request):
    request.session[SESSION_KEY] = time.time() + settings.REAUTH_MINUTES * 60
    token = request.session.get(TOKEN_KEY) or secrets.token_urlsafe(32)
    request.session[TOKEN_KEY] = token
    request.COOKIES[COOKIE_NAME] = token          # so checks later in this same request agree
    request._reauth_cookie = token                # the middleware sends it to the browser


def lock(request):
    request.session.pop(SESSION_KEY, None)
    request.session.pop(TOKEN_KEY, None)
    request.COOKIES.pop(COOKIE_NAME, None)
    request._reauth_cookie = None                 # the middleware removes it from the browser


class ReauthMiddleware:
    """Redirect signed-in users to the confirm-password page when opening a sensitive URL namespace."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if response is not None and hasattr(request, '_reauth_cookie'):
            token = request._reauth_cookie
            if token:
                # No max_age/expires: a browser-session cookie, gone when the browser is closed.
                response.set_cookie(COOKIE_NAME, token, httponly=True, samesite='Lax', secure=request.is_secure())
            else:
                response.delete_cookie(COOKIE_NAME)
        return response

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
