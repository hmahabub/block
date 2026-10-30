from django.urls import path

from .views import (
    DirectorCreateView,
    DirectorDetailView,
    DirectorListView,
    DirectorUpdateView,
    InvestmentSummaryView,
    TransactionCreateView,
    TransactionDeleteView,
    TransactionUpdateView,
)

app_name = 'directors'

urlpatterns = [
    path('', DirectorListView.as_view(), name='list'),
    path('create/', DirectorCreateView.as_view(), name='create'),
    path('<int:pk>/', DirectorDetailView.as_view(), name='detail'),
    path('<int:pk>/update/', DirectorUpdateView.as_view(), name='update'),
    path('summary/', InvestmentSummaryView.as_view(), name='summary'),
    path('transactions/new/', TransactionCreateView.as_view(), name='transaction-create'),
    path('transactions/<int:pk>/update/', TransactionUpdateView.as_view(), name='transaction-update'),
    path('transactions/<int:pk>/delete/', TransactionDeleteView.as_view(), name='transaction-delete'),
]
