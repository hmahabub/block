from . import context


def log_activity(user, action, obj, model_name=None, object_repr=None, changes=None, app_label=None):
    """Write one audit trail line.

    The model signals call this for every create, update and delete, so screens never need to. Call it directly only for a
    change that bypasses the model layer (a queryset .update(), which sends no signals).
    """
    from .models import ActivityLog

    if user is None:
        user = context.current_user()
    ActivityLog.objects.create(
        user=user if getattr(user, 'is_authenticated', False) else None,
        action=action,
        app_label=app_label or (obj._meta.app_label if obj is not None else ''),
        model_name=model_name or obj.__class__.__name__,
        object_id=str(obj.pk) if obj is not None else '',
        object_repr=(object_repr or (str(obj) if obj is not None else ''))[:255],
        changes=changes or {},
        ip_address=context.current_ip(),
    )
