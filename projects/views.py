from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views import View
from django.views.generic import CreateView, DeleteView, DetailView, FormView, ListView, UpdateView

from activity_log.services import log_activity
from core.mixins import CreateAuditMixin, DeleteAuditMixin, UpdateAuditMixin
from core.utils import int_or_none

from .forms import DecisionNoteForm, FlatDeletionRequestForm, FlatForm, GenerateFlatsForm, ProjectForm
from .models import Flat, FlatDeletionRequest, Project


def attach_active_sales(flats):
    """Give each flat an `active_sale` (customer, paid, balance) without re-querying per template access."""
    flats = list(flats)
    for flat in flats:
        flat.active_sale = flat.current_sale
    return flats


def build_booking_map(project):
    """Arrange the project's flats like a bus seat plan: top floor first, one column per unit letter.

    Returns (units, rows, others): `rows` is a list of (floor, [flat or None per unit]); `others` are
    older flats numbered without a unit letter, which cannot sit on the grid.
    """
    flats = attach_active_sales(project.flats.all())
    grid = {}
    others = []
    for flat in flats:
        if flat.unit:
            grid[(flat.floor_no, flat.unit)] = flat
        else:
            others.append(flat)
    units = sorted({unit for _, unit in grid})
    floors = sorted({floor for floor, _ in grid}, reverse=True)
    rows = [(floor, [grid.get((floor, unit)) for unit in units]) for floor in floors]
    return units, rows, others


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
        units, rows, others = build_booking_map(self.object)
        context['map_units'] = units
        context['map_rows'] = rows
        context['map_others'] = others
        context['flats'] = attach_active_sales(self.object.flats.all())
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


class GenerateFlatsView(PermissionRequiredMixin, FormView):
    """Create every flat of the building in one go: units (A, B, ...) x floors (1, 2, ...)."""

    form_class = GenerateFlatsForm
    template_name = 'projects/generate_flats.html'
    permission_required = 'projects.add_flat'

    def dispatch(self, request, *args, **kwargs):
        self.project = get_object_or_404(Project, pk=kwargs['project_pk'])
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['project'] = self.project
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['project'] = self.project
        return context

    @transaction.atomic
    def form_valid(self, form):
        floors, per_floor = form.cleaned_data['floors'], form.cleaned_data['units_per_floor']
        existing = set(self.project.flats.values_list('flat_no', flat=True))
        created = 0
        for floor in range(1, floors + 1):
            for index in range(per_floor):
                unit = chr(65 + index)
                if f'{unit}{floor}' in existing:
                    continue
                Flat.objects.create(project=self.project, unit=unit, floor_no=floor)
                created += 1
        if created:
            log_activity(self.request.user, 'created', self.project)
        messages.success(
            self.request,
            f'{created} flat(s) created for {self.project.project_name}.' if created else 'Every flat already exists.',
        )
        return HttpResponseRedirect(self.project.get_absolute_url())


class FlatListView(LoginRequiredMixin, ListView):
    model = Flat
    template_name = 'projects/flat_list.html'
    context_object_name = 'object_list'
    paginate_by = 30

    def get_queryset(self):
        queryset = super().get_queryset().select_related('project')
        q = self.request.GET.get('q')
        project_id = int_or_none(self.request.GET.get('project'))
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
        attach_active_sales(context['object_list'])
        return context


class FlatDetailView(LoginRequiredMixin, DetailView):
    model = Flat
    template_name = 'projects/flat_detail.html'
    context_object_name = 'object'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        flat = self.object
        context['direct_costs'] = flat.project_costs.select_related('cost_category', 'supplier')
        context['sales'] = flat.sales.select_related('customer', 'ref')
        context['deletion_blockers'] = flat.deletion_blockers()
        context['pending_request'] = flat.deletion_requests.filter(status=FlatDeletionRequest.Status.PENDING).first()
        context['can_request_deletion'] = FlatDeletionRequest.user_is_admin(self.request.user)
        return context


class FlatCreateView(PermissionRequiredMixin, CreateAuditMixin, CreateView):
    model = Flat
    form_class = FlatForm
    template_name = 'projects/flat_form.html'
    permission_required = 'projects.add_flat'

    def dispatch(self, request, *args, **kwargs):
        self.project = get_object_or_404(Project, pk=kwargs['project_pk'])
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['project'] = self.project
        return kwargs

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


# --- flat deletion: one admin requests, a different admin approves -----------------
class FlatDeletionRequestCreateView(LoginRequiredMixin, FormView):
    form_class = FlatDeletionRequestForm
    template_name = 'projects/flat_deletion_request_form.html'

    def dispatch(self, request, *args, **kwargs):
        self.flat = get_object_or_404(Flat, pk=kwargs['pk'])
        if request.user.is_authenticated and not FlatDeletionRequest.user_is_admin(request.user):
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['flat'] = self.flat
        context['blockers'] = self.flat.deletion_blockers()
        return context

    def form_valid(self, form):
        try:
            deletion = FlatDeletionRequest.open_for(self.flat, self.request.user, form.cleaned_data['reason'])
        except ValidationError as error:
            messages.error(self.request, ' '.join(error.messages))
            return redirect(self.flat)
        log_activity(self.request.user, 'created', deletion)
        messages.success(self.request, f'Deletion of {self.flat.flat_no} requested. A second admin must approve it.')
        return redirect('projects:deletion-requests')


class FlatDeletionRequestListView(LoginRequiredMixin, ListView):
    model = FlatDeletionRequest
    template_name = 'projects/flat_deletion_requests.html'
    context_object_name = 'object_list'
    paginate_by = 30

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['is_admin'] = FlatDeletionRequest.user_is_admin(self.request.user)
        context['decision_form'] = DecisionNoteForm()
        return context


class _DeletionDecisionView(LoginRequiredMixin, View):
    """POST-only: act on a pending deletion request."""

    http_method_names = ['post']

    def act(self, deletion, user, note):
        raise NotImplementedError

    def post(self, request, pk):
        deletion = get_object_or_404(FlatDeletionRequest, pk=pk)
        note = request.POST.get('note', '')[:300]
        try:
            message = self.act(deletion, request.user, note)
        except ValidationError as error:
            messages.error(request, ' '.join(error.messages))
        else:
            messages.success(request, message)
            log_activity(request.user, 'updated', deletion)
        return redirect('projects:deletion-requests')


class FlatDeletionApproveView(_DeletionDecisionView):
    def act(self, deletion, user, note):
        label = deletion.flat_label
        deletion.approve(user)
        log_activity(user, 'deleted', None, model_name='Flat', object_repr=label)
        return f'{label} was deleted.'


class FlatDeletionRejectView(_DeletionDecisionView):
    def act(self, deletion, user, note):
        deletion.reject(user, note)
        return 'The deletion request was rejected.'


class FlatDeletionWithdrawView(_DeletionDecisionView):
    def act(self, deletion, user, note):
        deletion.withdraw(user)
        return 'The deletion request was withdrawn.'
