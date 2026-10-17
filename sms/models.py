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
    gateway_id = models.CharField('Gateway message id', max_length=100, blank=True)
    sent_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']
        verbose_name = 'SMS'

    def __str__(self):
        return f'{self.get_kind_display()} to {self.phone} ({self.get_status_display()})'


class WhatsAppShare(models.Model):
    """Each time a user opened WhatsApp to send an invoice (the message itself is sent from WhatsApp)."""

    sale = models.ForeignKey('sales.FlatSale', on_delete=models.CASCADE, related_name='whatsapp_shares')
    customer = models.ForeignKey('customers.Customer', null=True, on_delete=models.SET_NULL, related_name='whatsapp_shares')
    phone = models.CharField('WhatsApp no.', max_length=20)
    opened_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']
        verbose_name = 'WhatsApp invoice'

    def __str__(self):
        return f'{self.sale.sale_no} to {self.phone}'
