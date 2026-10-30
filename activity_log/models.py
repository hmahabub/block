from django.apps import apps
from django.conf import settings
from django.db import models


class ActivityLog(models.Model):
    """One line of the audit trail: who created, changed or deleted what, when, and exactly what changed.

    Lines are written by signals on the models (see signals.py) and can never be edited or deleted.
    `changes` is {field name: [old value, new value]}; a created record has no old values, a deleted one no new ones.
    """

    ACTIONS = (
        ('created', 'Created'),
        ('updated', 'Updated'),
        ('deleted', 'Deleted'),
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='activity_logs',
    )
    action = models.CharField(max_length=10, choices=ACTIONS)
    app_label = models.CharField(max_length=60, blank=True)
    model_name = models.CharField(max_length=100)
    object_id = models.CharField(max_length=50, blank=True)
    object_repr = models.CharField(max_length=255, blank=True)
    changes = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']
        verbose_name = 'Audit Trail'
        verbose_name_plural = 'Audit Trail'
        indexes = [
            models.Index(fields=['app_label', 'model_name', 'object_id']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        who = self.user.get_full_name() or self.user.username if self.user else 'System'
        return f'{who} {self.action} {self.model_name} "{self.object_repr}"'

    # --- never edited, never deleted
    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise PermissionError('Audit trail entries cannot be changed.')
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError('Audit trail entries cannot be deleted.')

    # --- readable form
    @property
    def model_class(self):
        try:
            return apps.get_model(self.app_label, self.model_name)
        except LookupError:
            return None

    @property
    def model_label(self):
        """What the screens call this kind of record: a `Project` row is a Building, a `Development` a Project."""
        model = self.model_class
        return str(model._meta.verbose_name).title() if model else self.model_name

    def change_rows(self):
        """[(field label, old value, new value)] for display."""
        model = self.model_class
        rows = []
        for name, pair in (self.changes or {}).items():
            label = name.replace('_', ' ')
            label = label[:1].upper() + label[1:]
            if model is not None:
                try:
                    label = str(model._meta.get_field(name).verbose_name)
                    label = label[:1].upper() + label[1:]
                except Exception:  # noqa: BLE001 - a field removed since the entry was written
                    pass
            old, new = (pair + [None, None])[:2] if isinstance(pair, list) else (None, pair)
            rows.append((label, old, new))
        return rows
