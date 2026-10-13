from django.urls import path

from .views import ReminderView, SendRemindersView, SmsLogView

app_name = 'sms'

urlpatterns = [
    path('reminders/', ReminderView.as_view(), name='reminders'),
    path('reminders/send/', SendRemindersView.as_view(), name='send-reminders'),
    path('log/', SmsLogView.as_view(), name='log'),
]
