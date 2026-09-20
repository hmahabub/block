from django.urls import path

from .views import (
    CostCategoryCreateView,
    CostCategoryListView,
    CostCategoryUpdateView,
    ProjectBudgetCreateView,
    ProjectBudgetDeleteView,
    ProjectBudgetListView,
    ProjectBudgetUpdateView,
    ProjectCostCreateView,
    ProjectCostDeleteView,
    ProjectCostDetailView,
    ProjectCostListView,
    ProjectCostUpdateView,
)

app_name = 'costing'

urlpatterns = [
    path('categories/', CostCategoryListView.as_view(), name='category-list'),
    path('categories/create/', CostCategoryCreateView.as_view(), name='category-create'),
    path('categories/<int:pk>/update/', CostCategoryUpdateView.as_view(), name='category-update'),

    path('budgets/', ProjectBudgetListView.as_view(), name='budget-list'),
    path('budgets/create/', ProjectBudgetCreateView.as_view(), name='budget-create'),
    path('budgets/<int:pk>/update/', ProjectBudgetUpdateView.as_view(), name='budget-update'),
    path('budgets/<int:pk>/delete/', ProjectBudgetDeleteView.as_view(), name='budget-delete'),

    path('', ProjectCostListView.as_view(), name='cost-list'),
    path('create/', ProjectCostCreateView.as_view(), name='cost-create'),
    path('<int:pk>/', ProjectCostDetailView.as_view(), name='cost-detail'),
    path('<int:pk>/update/', ProjectCostUpdateView.as_view(), name='cost-update'),
    path('<int:pk>/delete/', ProjectCostDeleteView.as_view(), name='cost-delete'),
]
