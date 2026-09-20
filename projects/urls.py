from django.urls import path

from .views import (
    FlatCreateView,
    FlatDeleteView,
    FlatDetailView,
    FlatListView,
    FlatUpdateView,
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

    path('flats/', FlatListView.as_view(), name='flat-list'),
    path('<int:project_pk>/flats/create/', FlatCreateView.as_view(), name='flat-create'),
    path('flats/<int:pk>/', FlatDetailView.as_view(), name='flat-detail'),
    path('flats/<int:pk>/update/', FlatUpdateView.as_view(), name='flat-update'),
    path('flats/<int:pk>/delete/', FlatDeleteView.as_view(), name='flat-delete'),
]
