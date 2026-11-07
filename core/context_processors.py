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
    """`money_visible` is False while the sensitive screens are locked, so costs and sale/receipt figures stay off
    the pages shown to buyers. `entries_to_confirm` feeds the menu badge for people who can confirm book entries."""
    from .reauth import money_visible

    def pending():
        user = request.user
        if not (user.is_authenticated and user.has_perm('books.confirm_entries')):
            return 0
        from books.ledger import pending_count

        from .workspace import current_development

        return pending_count(current_development(request))

    return {'money_visible': lambda: money_visible(request), 'entries_to_confirm': pending}


def workspace(request):
    """The project the user is working in (None = every project), and the projects they can switch to."""
    from .workspace import current_development

    signed_in = getattr(getattr(request, 'user', None), 'is_authenticated', False)

    def choices():
        from projects.models import Development

        return list(Development.objects.all()) if signed_in else []

    return {
        'workspace_development': current_development(request) if signed_in else None,
        'workspace_choices': choices,
    }


def features(request):
    """Switches for features that can be turned off in .env."""
    from django.conf import settings

    return {'whatsapp_enabled': settings.WHATSAPP_ENABLED}


def company(request):
    # Lazy: the database is only queried on pages that actually use `company` (the printable documents).
    return {'company': SimpleLazyObject(CompanyProfile.current)}
