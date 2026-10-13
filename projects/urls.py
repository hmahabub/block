from django.urls import path

from .views import (
    FlatCreateView,
    FlatDeletionApproveView,
    FlatDeletionRejectView,
    FlatDeletionRequestCreateView,
    FlatDeletionRequestListView,
    FlatDeletionWithdrawView,
    FlatDetailView,
    FlatListView,
    FlatUpdateView,
    GenerateFlatsView,
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
    path('<int:project_pk>/flats/generate/', GenerateFlatsView.as_view(), name='flat-generate'),
    path('flats/<int:pk>/', FlatDetailView.as_view(), name='flat-detail'),
    path('flats/<int:pk>/update/', FlatUpdateView.as_view(), name='flat-update'),

    # A flat is never deleted directly: one admin requests, a different admin approves.
    path('flats/<int:pk>/request-deletion/', FlatDeletionRequestCreateView.as_view(), name='flat-request-deletion'),
    path('flat-deletions/', FlatDeletionRequestListView.as_view(), name='deletion-requests'),
    path('flat-deletions/<int:pk>/approve/', FlatDeletionApproveView.as_view(), name='deletion-approve'),
    path('flat-deletions/<int:pk>/reject/', FlatDeletionRejectView.as_view(), name='deletion-reject'),
    path('flat-deletions/<int:pk>/withdraw/', FlatDeletionWithdrawView.as_view(), name='deletion-withdraw'),
]
