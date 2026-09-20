from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.urls import reverse_lazy
from django.views.generic import CreateView, DeleteView, DetailView, ListView, UpdateView

from core.mixins import CreateAuditMixin, DeleteAuditMixin, UpdateAuditMixin

from .forms import FlatForm, ProjectForm
from .models import Flat, Project


class ProjectListView(LoginRequiredMixin, ListView):
    model = Project
    template_name = 'projects/project_list.html'
    context_object_name = 'object_list'
    paginate_by = 15

    def get_queryset(self):
        queryset = super().get_queryset()
        q = self.request.GET.get('q')
        status = self.request.GET.get('status')
        if q:
            queryset = queryset.filter(Q(project_name__icontains=q) | Q(project_code__icontains=q) | Q(location__icontains=q))
        if status:
            queryset = queryset.filter(status=status)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['status_choices'] = Project.Status.choices
        return context


class ProjectDetailView(LoginRequiredMixin, DetailView):
    model = Project
    template_name = 'projects/project_detail.html'
    context_object_name = 'object'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['flats'] = self.object.flats.all()
        return context


class ProjectCreateView(PermissionRequiredMixin, CreateAuditMixin, CreateView):
    model = Project
    form_class = ProjectForm
    template_name = 'projects/project_form.html'
    permission_required = 'projects.add_project'

    def get_success_url(self):
        return reverse_lazy('projects:detail', kwargs={'pk': self.object.pk})


class ProjectUpdateView(PermissionRequiredMixin, UpdateAuditMixin, UpdateView):
    model = Project
    form_class = ProjectForm
    template_name = 'projects/project_form.html'
    permission_required = 'projects.change_project'

    def get_success_url(self):
        return reverse_lazy('projects:detail', kwargs={'pk': self.object.pk})


class ProjectDeleteView(PermissionRequiredMixin, DeleteAuditMixin, DeleteView):
    model = Project
    template_name = 'projects/project_confirm_delete.html'
    success_url = reverse_lazy('projects:list')
    permission_required = 'projects.delete_project'


class FlatListView(LoginRequiredMixin, ListView):
    model = Flat
    template_name = 'projects/flat_list.html'
    context_object_name = 'object_list'
    paginate_by = 30

    def get_queryset(self):
        queryset = super().get_queryset().select_related('project')
        q = self.request.GET.get('q')
        project_id = self.request.GET.get('project')
        status = self.request.GET.get('status')
        if q:
            queryset = queryset.filter(Q(flat_no__icontains=q) | Q(project__project_name__icontains=q))
        if project_id:
            queryset = queryset.filter(project_id=project_id)
        if status:
            queryset = queryset.filter(status=status)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['projects'] = Project.objects.all()
        context['status_choices'] = Flat.Status.choices
        return context


class FlatDetailView(LoginRequiredMixin, DetailView):
    model = Flat
    template_name = 'projects/flat_detail.html'
    context_object_name = 'object'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['cost_allocations'] = self.object.cost_allocations.select_related('project_cost__cost_category')
        context['direct_costs'] = self.object.project_costs.select_related('cost_category', 'supplier')
        context['sales'] = self.object.sales.select_related('customer')
        return context


class FlatCreateView(PermissionRequiredMixin, CreateAuditMixin, CreateView):
    model = Flat
    form_class = FlatForm
    template_name = 'projects/flat_form.html'
    permission_required = 'projects.add_flat'

    def dispatch(self, request, *args, **kwargs):
        self.project = get_object_or_404(Project, pk=kwargs['project_pk'])
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        form.instance.project = self.project
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['project'] = self.project
        return context

    def get_success_url(self):
        return reverse_lazy('projects:detail', kwargs={'pk': self.project.pk})


class FlatUpdateView(PermissionRequiredMixin, UpdateAuditMixin, UpdateView):
    model = Flat
    form_class = FlatForm
    template_name = 'projects/flat_form.html'
    permission_required = 'projects.change_flat'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['project'] = self.object.project
        return context

    def get_success_url(self):
        return reverse_lazy('projects:flat-detail', kwargs={'pk': self.object.pk})


class FlatDeleteView(PermissionRequiredMixin, DeleteAuditMixin, DeleteView):
    model = Flat
    template_name = 'projects/flat_confirm_delete.html'
    permission_required = 'projects.delete_flat'

    def get_success_url(self):
        return reverse_lazy('projects:detail', kwargs={'pk': self.object.project.pk})
