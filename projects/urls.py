from django.urls import path

from .views import (
    ApartmentCreateView,
    ApartmentDeleteView,
    ApartmentDetailView,
    ApartmentListView,
    ApartmentUpdateView,
    ProjectCreateView,
    ProjectDeleteView,
    ProjectDetailView,
    ProjectListView,
    ProjectUpdateView,
)

app_name = 'projects'

urlpatterns = [
    path('', ProjectListView.as_view(), name='list'),
    path('create/', ProjectCreateView.as_view(), name='create'),
    path('<int:pk>/', ProjectDetailView.as_view(), name='detail'),
    path('<int:pk>/update/', ProjectUpdateView.as_view(), name='update'),
    path('<int:pk>/delete/', ProjectDeleteView.as_view(), name='delete'),

    path('apartments/', ApartmentListView.as_view(), name='apartment-list'),
    path('<int:project_pk>/apartments/create/', ApartmentCreateView.as_view(), name='apartment-create'),
    path('apartments/<int:pk>/', ApartmentDetailView.as_view(), name='apartment-detail'),
    path('apartments/<int:pk>/update/', ApartmentUpdateView.as_view(), name='apartment-update'),
    path('apartments/<int:pk>/delete/', ApartmentDeleteView.as_view(), name='apartment-delete'),
]
