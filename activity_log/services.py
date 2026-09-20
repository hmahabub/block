def log_activity(user, action, obj, model_name=None, object_repr=None):
    """Explicitly record a create/update/delete for the recent-activity feed.

    Called from core.mixins audit mixins rather than from a blind global
    post_save/post_delete signal, so `user` is always the request's actual
    user instead of silently ending up None.
    """
    from .models import ActivityLog

    ActivityLog.objects.create(
        user=user if getattr(user, 'is_authenticated', False) else None,
        action=action,
        model_name=model_name or obj.__class__.__name__,
        object_id=str(obj.pk) if obj is not None else '',
        object_repr=object_repr or (str(obj) if obj is not None else ''),
    )
