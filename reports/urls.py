from django.urls import path

from .views import (
    ApartmentWisePDFView,
    ApartmentWiseReportView,
    DuesReportView,
    ProjectProfitabilityReportView,
    ReportIndexView,
)

app_name = 'reports'

urlpatterns = [
    path('', ReportIndexView.as_view(), name='index'),
    path('project-profitability/', ProjectProfitabilityReportView.as_view(), name='project-profitability'),
    path('apartment-wise/', ApartmentWiseReportView.as_view(), name='apartment-wise'),
    path('apartment-wise/<int:project_pk>/pdf/', ApartmentWisePDFView.as_view(), name='apartment-wise-pdf'),
    path('dues/', DuesReportView.as_view(), name='dues'),
]
