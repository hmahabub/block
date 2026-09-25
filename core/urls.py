from django.urls import path

from .views import CompanySettingsView

app_name = 'core'

urlpatterns = [
    path('', CompanySettingsView.as_view(), name='company-settings'),
]
