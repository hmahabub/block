"""Small helpers shared by the test suites."""
import time

from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.sessions.backends.db import SessionStore
from django.test import RequestFactory


def unlock_client(client, minutes=60):
    """Mark a logged-in test client as having re-entered its password (see core.reauth)."""
    session = client.session
    session['reauth_until'] = time.time() + minutes * 60
    session.save()


def make_request(user=None, path='/', method='get', data=None, session=None):
    """A request with session and messages attached, for calling views/middleware directly."""
    factory = RequestFactory()
    request = getattr(factory, method)(path, data or {})
    request.session = SessionStore()
    request.session.update(session or {})
    request._messages = FallbackStorage(request)
    if user is not None:
        request.user = user
    return request
