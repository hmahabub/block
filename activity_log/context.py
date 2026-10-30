"""Who is making the change right now, so the audit trail can say.

The middleware stores the current request here for the duration of the request; model signals read it. Outside a
request (management commands, the shell, migrations) there is no user and the entry is recorded as "System".
"""
from contextlib import contextmanager
from contextvars import ContextVar

_request = ContextVar('audit_request', default=None)
_override = ContextVar('audit_override', default=None)


def set_request(request):
    return _request.set(request)


def reset_request(token):
    _request.reset(token)


@contextmanager
def acting_as(user, ip=None):
    """Attribute changes made inside the block to `user` (used by scripts and tests that have no request)."""
    token = _override.set((user, ip))
    try:
        yield
    finally:
        _override.reset(token)


def current_user():
    override = _override.get()
    if override is not None:
        return override[0]
    request = _request.get()
    user = getattr(request, 'user', None) if request is not None else None
    return user if getattr(user, 'is_authenticated', False) else None


def current_ip():
    override = _override.get()
    if override is not None:
        return override[1]
    request = _request.get()
    if request is None:
        return None
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '')
    address = forwarded.split(',')[0].strip() if forwarded else request.META.get('REMOTE_ADDR')
    return address or None
