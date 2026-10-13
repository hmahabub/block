from django.utils.functional import SimpleLazyObject

from .models import CompanyProfile


def flat_deletion_pending(request):
    """Number of flat deletion requests waiting for a second admin (shown as a badge in the menu)."""
    def count():
        from projects.models import FlatDeletionRequest

        user = request.user
        if not (user.is_authenticated and FlatDeletionRequest.user_is_admin(user)):
            return 0
        return FlatDeletionRequest.objects.filter(status=FlatDeletionRequest.Status.PENDING).exclude(requested_by=user).count()

    return {'flat_deletions_waiting': count}


def reauth_state(request):
    """`costs_visible` is False while Costing is locked, so cost figures stay off the pages shown to buyers."""
    from django.conf import settings

    from .reauth import is_unlocked

    def visible():
        return 'costing' not in settings.SENSITIVE_NAMESPACES or is_unlocked(request)

    return {'costs_visible': visible}


def company(request):
    # Lazy: the database is only queried on pages that actually use `company` (the printable documents).
    return {'company': SimpleLazyObject(CompanyProfile.current)}
