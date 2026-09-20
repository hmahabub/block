from django.urls import path

from .views import (
    ApartmentSaleCreateView,
    ApartmentSaleDetailView,
    ApartmentSaleListView,
    ApartmentSaleUpdateView,
    CustomerPaymentCreateView,
    CustomerPaymentListView,
)

app_name = 'sales'

urlpatterns = [
    path('', ApartmentSaleListView.as_view(), name='list'),
    path('create/', ApartmentSaleCreateView.as_view(), name='create'),
    path('<int:pk>/', ApartmentSaleDetailView.as_view(), name='detail'),
    path('<int:pk>/update/', ApartmentSaleUpdateView.as_view(), name='update'),

    path('payments/', CustomerPaymentListView.as_view(), name='payment-list'),
    path('payments/create/', CustomerPaymentCreateView.as_view(), name='payment-create'),
]
