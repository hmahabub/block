from django.urls import path

from .views import (
    SupplierCreateView,
    SupplierDeleteView,
    SupplierDetailView,
    SupplierListView,
    SupplierUpdateView,
)

app_name = 'suppliers'

urlpatterns = [
    path('', SupplierListView.as_view(), name='list'),
    path('create/', SupplierCreateView.as_view(), name='create'),
    path('<int:pk>/', SupplierDetailView.as_view(), name='detail'),
    path('<int:pk>/update/', SupplierUpdateView.as_view(), name='update'),
    path('<int:pk>/delete/', SupplierDeleteView.as_view(), name='delete'),
]
