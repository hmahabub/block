from django.urls import path

from .views import (
    CustomerPostReportView,
    CustomerWiseReportView,
    DailyCostReportView,
    DailyTransactionsView,
    DuesReportView,
    FinanceReportView,
    FlatWiseReportView,
    PeriodicCollectionReportView,
    ProfitabilityReportView,
    ProfitLossReportView,
    ReportIndexView,
)

app_name = 'reports'

urlpatterns = [
    path('', ReportIndexView.as_view(), name='index'),
    path('daily/', DailyTransactionsView.as_view(), name='daily'),
    path('daily-costs/', DailyCostReportView.as_view(), name='daily-costs'),
    path('profitability/', ProfitabilityReportView.as_view(), name='profitability'),
    path('finance/', FinanceReportView.as_view(), name='finance'),
    path('collection/', PeriodicCollectionReportView.as_view(), name='collection'),
    path('profit-loss/', ProfitLossReportView.as_view(), name='profit-loss'),
    path('customers/', CustomerPostReportView.as_view(), name='customers'),
    path('customer-wise/', CustomerWiseReportView.as_view(), name='customer-wise'),
    path('flat-wise/', FlatWiseReportView.as_view(), name='flat-wise'),
    path('dues/', DuesReportView.as_view(), name='dues'),
]
