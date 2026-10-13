from django.conf import settings
from django.db import models


class SmsLog(models.Model):
    """Every SMS the system tried to send, so there is always a record of what a customer was told."""

    class Kind(models.TextChoices):
        PAYMENT = 'PAYMENT', 'Payment confirmation'
        REMINDER = 'REMINDER', 'Balance reminder'

    class Status(models.TextChoices):
        SENT = 'SENT', 'Sent'
        LOGGED = 'LOGGED', 'Logged only (no gateway configured)'
        FAILED = 'FAILED', 'Failed'

    customer = models.ForeignKey('customers.Customer', null=True, on_delete=models.SET_NULL, related_name='sms_logs')
    phone = models.CharField(max_length=20)
    kind = models.CharField(max_length=10, choices=Kind.choices)
    message = models.TextField()
    status = models.CharField(max_length=10, choices=Status.choices)
    error = models.CharField(max_length=300, blank=True)
    sent_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']
        verbose_name = 'SMS'

    def __str__(self):
        return f'{self.get_kind_display()} to {self.phone} ({self.get_status_display()})'
