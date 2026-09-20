from django.urls import path

from .views import (
    DuesReportView,
    FlatWisePDFView,
    FlatWiseReportView,
    ProjectProfitabilityReportView,
    ReportIndexView,
)

app_name = 'reports'

urlpatterns = [
    path('', ReportIndexView.as_view(), name='index'),
    path('project-profitability/', ProjectProfitabilityReportView.as_view(), name='project-profitability'),
    path('flat-wise/', FlatWiseReportView.as_view(), name='flat-wise'),
    path('flat-wise/<int:project_pk>/pdf/', FlatWisePDFView.as_view(), name='flat-wise-pdf'),
    path('dues/', DuesReportView.as_view(), name='dues'),
]
