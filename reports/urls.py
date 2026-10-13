from django.urls import path

from .views import (
    CustomerPostReportView,
    DuesReportView,
    FinanceReportView,
    FlatWiseReportView,
    PeriodicCollectionReportView,
    ProfitLossReportView,
    ReportIndexView,
)

app_name = 'reports'

urlpatterns = [
    path('', ReportIndexView.as_view(), name='index'),
    path('finance/', FinanceReportView.as_view(), name='finance'),
    path('collection/', PeriodicCollectionReportView.as_view(), name='collection'),
    path('profit-loss/', ProfitLossReportView.as_view(), name='profit-loss'),
    path('customers/', CustomerPostReportView.as_view(), name='customers'),
    path('flat-wise/', FlatWiseReportView.as_view(), name='flat-wise'),
    path('dues/', DuesReportView.as_view(), name='dues'),
]
