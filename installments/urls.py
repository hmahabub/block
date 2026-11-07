from django.urls import path

from .views import (
    InstallmentDetailView,
    InstallmentIssueView,
    InstallmentListView,
    InstallmentSendSmsView,
    InstallmentWithdrawView,
)

app_name = 'installments'

urlpatterns = [
    path('', InstallmentListView.as_view(), name='list'),
    path('issue/', InstallmentIssueView.as_view(), name='issue'),
    path('<int:pk>/', InstallmentDetailView.as_view(), name='detail'),
    path('<int:pk>/send-sms/', InstallmentSendSmsView.as_view(), name='send-sms'),
    path('<int:pk>/withdraw/', InstallmentWithdrawView.as_view(), name='withdraw'),
]
