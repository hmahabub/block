from django.urls import path

from .views import (
    BankAccountCreateView,
    BankAccountListView,
    BankBookCreateView,
    BankBookListView,
    CashBookCreateView,
    CashBookListView,
)

app_name = 'books'

urlpatterns = [
    path('cashbook/', CashBookListView.as_view(), name='cashbook_list'),
    path('cashbook/new/', CashBookCreateView.as_view(), name='cashbook_create'),
    path('bankbook/', BankBookListView.as_view(), name='bankbook_list'),
    path('bankbook/new/', BankBookCreateView.as_view(), name='bankbook_create'),
    path('bankaccounts/', BankAccountListView.as_view(), name='bankaccount_list'),
    path('bankaccounts/new/', BankAccountCreateView.as_view(), name='bankaccount_create'),
]
