from django.urls import path

from .views import ReminderView, SendRemindersView, SmsBalanceView, SmsLogView, WhatsAppInvoicesView, WhatsAppSendView

app_name = 'sms'

urlpatterns = [
    path('reminders/', ReminderView.as_view(), name='reminders'),
    path('reminders/send/', SendRemindersView.as_view(), name='send-reminders'),
    path('log/', SmsLogView.as_view(), name='log'),
    path('balance/', SmsBalanceView.as_view(), name='balance'),
    path('whatsapp/', WhatsAppInvoicesView.as_view(), name='whatsapp-invoices'),
    path('whatsapp/<int:pk>/send/', WhatsAppSendView.as_view(), name='whatsapp-send'),
]
