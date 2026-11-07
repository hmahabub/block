"""The audit trail: every create, update and delete of the business records, recorded from the model layer.

Doing it here (not in the screens) means a change is recorded however it was made: a form, the admin site, a payment that
recalculates a sale, a management command. The only things that escape are raw queryset .update() calls and bulk_create,
which Django sends no signals for; the few places that use them log explicitly.
"""
import datetime
from decimal import Decimal

from django.apps import apps
from django.db.models.signals import m2m_changed, post_delete, post_save, pre_delete, pre_save

from .services import log_activity

# Everything in these apps is tracked, plus the user accounts and groups. The rest (sessions, the numbering counters, the
# SMS and WhatsApp send logs, the audit trail itself) is system bookkeeping, not business records.
TRACKED_APPS = {'customers', 'suppliers', 'projects', 'costing', 'sales', 'books', 'directors', 'installments'}
TRACKED_MODELS = {'core.CompanyProfile', 'auth.User', 'auth.Group'}
IGNORED_MODELS = {'core.Sequence', 'sms.SmsLog', 'sms.WhatsAppShare', 'activity_log.ActivityLog'}

# Never worth a line on their own (or must never be written out).
NOISE_FIELDS = {'created_at', 'updated_at', 'last_login'}
SECRET_FIELDS = {'password'}
MAX_VALUE = 500


def is_tracked(model):
    label = model._meta.label
    if label in IGNORED_MODELS:
        return False
    return model._meta.app_label in TRACKED_APPS or label in TRACKED_MODELS


def _plain(field, value):
    """A value in a comparable, JSON-friendly form (so 100 and Decimal('100.00') are the same, '2026-01-01' a date)."""
    if value is None:
        return None
    try:
        value = field.to_python(value)
    except Exception:  # noqa: BLE001
        pass
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float, Decimal)):
        return format(Decimal(str(value)).normalize(), 'f')
    if isinstance(value, datetime.datetime):
        return value.replace(microsecond=0).isoformat()
    if isinstance(value, datetime.date):
        return value.isoformat()
    text = str(value)
    return text if len(text) <= MAX_VALUE else text[:MAX_VALUE] + '...'


def _tracked_fields(model):
    return [f for f in model._meta.concrete_fields if f.name not in NOISE_FIELDS and not f.primary_key]


def _snapshot(instance, fields=None):
    return {f.name: _plain(f, getattr(instance, f.attname)) for f in (fields or _tracked_fields(instance._meta.model))}


def _mask(name, value):
    return '(changed)' if name in SECRET_FIELDS and value is not None else value


def _diff(model, before, after):
    changes = {}
    for field in _tracked_fields(model):
        old, new = before.get(field.name), after.get(field.name)
        if old != new:
            changes[field.name] = [_mask(field.name, old), _mask(field.name, new)]
    return changes


def _repr(instance):
    try:
        return str(instance)[:255]
    except Exception:  # noqa: BLE001 - a record whose related rows are already gone
        return f'{instance._meta.verbose_name} {instance.pk}'


def before_save(sender, instance, raw=False, **kwargs):
    if raw or not is_tracked(sender):
        return
    instance._audit_before = None
    if instance.pk is not None:
        row = sender._base_manager.filter(pk=instance.pk).first()
        if row is not None:
            instance._audit_before = _snapshot(row)


def after_save(sender, instance, created, raw=False, **kwargs):
    if raw or not is_tracked(sender):
        return
    after = _snapshot(instance)
    if created or getattr(instance, '_audit_before', None) is None:
        changes = {name: [None, _mask(name, value)] for name, value in after.items() if value not in (None, '')}
        log_activity(None, 'created', instance, changes=changes)
        return
    changes = _diff(sender, instance._audit_before, after)
    instance._audit_before = None
    if changes:
        log_activity(None, 'updated', instance, changes=changes)


def before_delete(sender, instance, **kwargs):
    if is_tracked(sender):
        instance._audit_repr = _repr(instance)
        instance._audit_snapshot = _snapshot(instance)


def after_delete(sender, instance, **kwargs):
    if not is_tracked(sender):
        return
    values = getattr(instance, '_audit_snapshot', None) or _snapshot(instance)
    changes = {name: [_mask(name, value), None] for name, value in values.items() if value not in (None, '')}
    log_activity(None, 'deleted', instance, object_repr=getattr(instance, '_audit_repr', None) or _repr(instance), changes=changes)


def members_changed(sender, instance, action, pk_set, reverse, model, **kwargs):
    """Group membership and permissions: who was given or lost what."""
    if action not in ('post_add', 'post_remove', 'post_clear') or reverse or not is_tracked(instance.__class__):
        return
    field = next((f.name for f in instance._meta.many_to_many if f.remote_field.through is sender), 'members')
    ids = sorted(pk_set) if pk_set else []
    change = {'added': ids, 'removed': []} if action == 'post_add' else {'added': [], 'removed': ids}
    if action == 'post_clear':
        change = {'added': [], 'removed': ['all']}
    log_activity(None, 'updated', instance, changes={field: [change['removed'] or None, change['added'] or None]})


def connect():
    for model in apps.get_models():
        if is_tracked(model):
            uid = f'audit-{model._meta.label}'
            pre_save.connect(before_save, sender=model, dispatch_uid=f'{uid}-pre-save')
            post_save.connect(after_save, sender=model, dispatch_uid=f'{uid}-post-save')
            pre_delete.connect(before_delete, sender=model, dispatch_uid=f'{uid}-pre-delete')
            post_delete.connect(after_delete, sender=model, dispatch_uid=f'{uid}-post-delete')
            for field in model._meta.many_to_many:
                m2m_changed.connect(members_changed, sender=field.remote_field.through, dispatch_uid=f'{uid}-{field.name}-m2m')
