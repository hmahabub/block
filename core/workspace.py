"""The project workspace.

A user can "enter" a project (a `projects.Development`). While inside it, every screen shows only that project's
buildings, flats, costs, budgets, sales, payments, book entries and director money, and every form offers only that
project's buildings and flats. "Exit project" goes back to the company-wide view. The choice lives in the session,
so it is per user and per browser, and it is gone after logout.

Customers, suppliers and directors are shared by every project, so they are never filtered. Everything else belongs to
one project at a time: outside a project those screens are closed (`WorkspaceGateMiddleware`) and the user is sent to
the home page to open one, so no figure ever adds up several projects.

Views take part by adding `WorkspaceMixin` and naming the path from their model to the project:

    class FlatListView(WorkspaceMixin, LoginRequiredMixin, ListView):
        workspace_lookup = 'project__development'
"""
from django.contrib import messages
from django.forms import ModelChoiceField
from django.shortcuts import redirect

SESSION_KEY = 'workspace_development'


def current_development(request):
    """The project the user is working in, or None for the company-wide view."""
    if hasattr(request, '_workspace_development'):
        return request._workspace_development
    development = None
    session = getattr(request, 'session', None)
    pk = session.get(SESSION_KEY) if session is not None else None
    if pk:
        from projects.models import Development

        development = Development.objects.filter(pk=pk).first()
        if development is None:
            session.pop(SESSION_KEY, None)  # the project was deleted meanwhile
    request._workspace_development = development
    return development


def enter(request, development):
    request.session[SESSION_KEY] = development.pk
    request._workspace_development = development


def leave(request):
    request.session.pop(SESSION_KEY, None)
    request._workspace_development = None


def in_workspace(queryset, request, lookup):
    """Narrow a queryset to the current project; `lookup` is the path from the model to its Development."""
    development = current_development(request)
    return queryset.filter(**{lookup: development}) if development else queryset


def limit_form(form, development):
    """Offer only this project's buildings, flats, sales and project in a form's choice fields."""
    if development is None:
        return form
    from projects.models import Development, Flat, Project
    from sales.models import FlatSale

    paths = {Project: 'development', Flat: 'project__development', FlatSale: 'project__development', Development: 'pk'}
    for name, field in form.fields.items():
        if not isinstance(field, ModelChoiceField):
            continue
        path = paths.get(field.queryset.model)
        if path is None:
            continue
        value = development.pk if path == 'pk' else development
        field.queryset = field.queryset.filter(**{path: value})
        if path in ('pk', 'development') and not form.is_bound and not form.initial.get(name) and not getattr(getattr(form, 'instance', None), name + '_id', None):
            choices = list(field.queryset[:2])
            if len(choices) == 1:
                form.initial[name] = choices[0].pk
    return form


class WorkspaceMixin:
    """Put it before the generic view. Lists, details, edits and deletes only reach the current project's records,
    and forms only offer its buildings, flats and sales."""

    workspace_lookup = None

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.workspace_lookup:
            queryset = in_workspace(queryset, self.request, self.workspace_lookup)
        return queryset

    def get_form(self, form_class=None):
        return limit_form(super().get_form(form_class), current_development(self.request))


# Screens that exist outside a project. Everything else in these apps needs a project to be open.
OPEN_SCREENS = {
    'projects': {'development-list', 'development-create', 'development-detail', 'development-update', 'development-delete'},
    'costing': {'category-list', 'category-create', 'category-update'},
    'sales': {'reference-list', 'reference-create', 'reference-update', 'invoice-shared'},
    'books': {'accounts', 'account-create', 'account-update', 'transfers', 'transfer-create', 'transfer-delete'},
}
PROJECT_ONLY_SCREENS = {'sms': {'reminders', 'send-reminders', 'whatsapp-invoices', 'whatsapp-send'}}
PROJECT_APPS = {'projects', 'costing', 'sales', 'books', 'reports', 'installments'}


def needs_project(namespace, name):
    if namespace in PROJECT_APPS:
        return name not in OPEN_SCREENS.get(namespace, ())
    return name in PROJECT_ONLY_SCREENS.get(namespace, ())


class WorkspaceGateMiddleware:
    """Signed-in users reach the per-project screens only while a project is open."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        match = request.resolver_match
        if not match or not request.user.is_authenticated:
            return None
        namespace = match.namespaces[0] if match.namespaces else ''
        if not needs_project(namespace, match.url_name) or current_development(request):
            return None
        messages.info(request, 'Open a project first: this part works inside one project at a time.')
        return redirect('home')
