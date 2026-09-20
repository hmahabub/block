from django.urls import path

from .views import (
    CustomerPaymentCreateView,
    CustomerPaymentListView,
    FlatSaleCreateView,
    FlatSaleDetailView,
    FlatSaleListView,
    FlatSaleUpdateView,
)

app_name = 'sales'

urlpatterns = [
    path('', FlatSaleListView.as_view(), name='list'),
    path('create/', FlatSaleCreateView.as_view(), name='create'),
    path('<int:pk>/', FlatSaleDetailView.as_view(), name='detail'),
    path('<int:pk>/update/', FlatSaleUpdateView.as_view(), name='update'),

    path('payments/', CustomerPaymentListView.as_view(), name='payment-list'),
    path('payments/create/', CustomerPaymentCreateView.as_view(), name='payment-create'),
]
