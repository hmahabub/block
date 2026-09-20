from django.urls import path

from .views import SupplierPaymentCreateView, SupplierPaymentListView

app_name = 'payables'

urlpatterns = [
    path('', SupplierPaymentListView.as_view(), name='list'),
    path('create/', SupplierPaymentCreateView.as_view(), name='create'),
]
