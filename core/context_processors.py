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

        return pending_count()

    return {'money_visible': lambda: money_visible(request), 'entries_to_confirm': pending}


def company(request):
    # Lazy: the database is only queried on pages that actually use `company` (the printable documents).
    return {'company': SimpleLazyObject(CompanyProfile.current)}
