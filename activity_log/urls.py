from django.urls import path

from .views import ActivityLogListView

app_name = 'activity_log'

urlpatterns = [
    path('', ActivityLogListView.as_view(), name='list'),
]
