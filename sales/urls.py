from django.urls import path

from .views import (
    CustomerPaymentCreateView,
    CustomerPaymentListView,
    CustomerPaymentReceiptView,
    FlatSaleCancelView,
    FlatSaleCreateView,
    FlatSaleDetailView,
    FlatSaleInvoiceView,
    FlatSaleListView,
    FlatSaleUpdateView,
    HonorariumPaymentCreateView,
    RefundPaymentCreateView,
    ReferenceCreateView,
    ReferenceDetailView,
    ReferenceListView,
    ReferenceUpdateView,
)

app_name = 'sales'

urlpatterns = [
    path('', FlatSaleListView.as_view(), name='list'),
    path('create/', FlatSaleCreateView.as_view(), name='create'),
    path('<int:pk>/', FlatSaleDetailView.as_view(), name='detail'),
    path('<int:pk>/update/', FlatSaleUpdateView.as_view(), name='update'),
    path('<int:pk>/cancel/', FlatSaleCancelView.as_view(), name='cancel'),
    path('<int:pk>/honorarium/', HonorariumPaymentCreateView.as_view(), name='honorarium-create'),
    path('<int:pk>/refund/', RefundPaymentCreateView.as_view(), name='refund-create'),

    path('<int:pk>/invoice/', FlatSaleInvoiceView.as_view(), name='invoice'),

    path('payments/', CustomerPaymentListView.as_view(), name='payment-list'),
    path('payments/create/', CustomerPaymentCreateView.as_view(), name='payment-create'),
    path('payments/<int:pk>/receipt/', CustomerPaymentReceiptView.as_view(), name='payment-receipt'),

    path('references/', ReferenceListView.as_view(), name='reference-list'),
    path('references/create/', ReferenceCreateView.as_view(), name='reference-create'),
    path('references/<int:pk>/', ReferenceDetailView.as_view(), name='reference-detail'),
    path('references/<int:pk>/update/', ReferenceUpdateView.as_view(), name='reference-update'),
]
