"""Small helpers shared by the test suites."""
import time

from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.sessions.backends.db import SessionStore
from django.test import RequestFactory


def unlock_client(client, minutes=60):
    """Mark a logged-in test client as having re-entered its password (see core.reauth)."""
    session = client.session
    session['reauth_until'] = time.time() + minutes * 60
    session['reauth_token'] = 'test-token'
    session.save()
    client.cookies['daj_unlocked'] = 'test-token'


def make_request(user=None, path='/', method='get', data=None, session=None, cookies=None):
    """A request with session and messages attached, for calling views/middleware directly."""
    factory = RequestFactory()
    request = getattr(factory, method)(path, data or {})
    request.COOKIES.update(cookies or {})
    request.session = SessionStore()
    request.session.update(session or {})
    request._messages = FallbackStorage(request)
    if user is not None:
        request.user = user
    return request


def make_project(name='P', floors=2, units=2, base=1000, quoted=1200, parking=100, area=1000, **extra):
    """A project with identical flats named A1, B1, A2, B2 ... (unit letter + floor)."""
    from projects.models import Flat, Project

    project = Project.objects.create(
        project_name=name, floor_no=floors, flat_area=area, base_price=base, quoted_price=quoted,
        parking_price=parking, **extra,
    )
    flats = [
        Flat.objects.create(project=project, unit=chr(65 + index), floor_no=floor)
        for floor in range(1, floors + 1) for index in range(units)
    ]
    return project, flats


def make_account(name='Bank 1', **extra):
    from books.models import Account

    return Account.objects.create(name=name, **extra)
