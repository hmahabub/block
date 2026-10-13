from django.contrib.sessions.models import Session
from django.utils import timezone


def end_all_sessions(user):
    """Delete every login session of `user`, on every device and browser. Returns how many were ended."""
    key = str(user.pk)
    ended = 0
    for session in Session.objects.filter(expire_date__gt=timezone.now()):
        if session.get_decoded().get('_auth_user_id') == key:
            session.delete()
            ended += 1
    return ended
