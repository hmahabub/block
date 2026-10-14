from django.urls import path

from .views import (
    AccountCreateView,
    AccountListView,
    AccountUpdateView,
    AssignAccountView,
    BookView,
    ConfirmEntriesView,
    ConfirmPageView,
    TransferCreateView,
    TransferDeleteView,
    TransferListView,
)

app_name = 'books'

urlpatterns = [
    path('', BookView.as_view(), name='book'),
    path('account/<int:pk>/', BookView.as_view(), name='ledger'),
    path('confirm-entries/', ConfirmPageView.as_view(), name='to-confirm'),
    path('confirm/', ConfirmEntriesView.as_view(), name='confirm'),
    path('assign-account/', AssignAccountView.as_view(), name='assign-account'),

    path('accounts/', AccountListView.as_view(), name='accounts'),
    path('accounts/new/', AccountCreateView.as_view(), name='account-create'),
    path('accounts/<int:pk>/update/', AccountUpdateView.as_view(), name='account-update'),

    path('transfers/', TransferListView.as_view(), name='transfers'),
    path('transfers/new/', TransferCreateView.as_view(), name='transfer-create'),
    path('transfers/<int:pk>/delete/', TransferDeleteView.as_view(), name='transfer-delete'),
]
