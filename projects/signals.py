from django.db.models import ProtectedError
from django.db.models.signals import pre_delete
from django.dispatch import receiver

from .models import Flat


@receiver(pre_delete, sender=Flat)
def protect_flats_from_deletion(sender, instance, **kwargs):
    """Delete protection: a flat can only go through an approved FlatDeletionRequest.

    Applies to every way of deleting (shell, admin, bulk deletes), not just the screens.
    """
    if not getattr(instance, '_deletion_approved', False):
        raise ProtectedError(
            'Flats can only be deleted through an approved deletion request (two admins).', {instance},
        )
