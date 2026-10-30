from django.apps import AppConfig


class ActivityLogConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'activity_log'
    verbose_name = 'Audit Trail'

    def ready(self):
        from . import signals

        signals.connect()
