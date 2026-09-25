import calendar
import datetime

from django.db.models import Q

from projects.models import Project


def parse_date(value):
    try:
        return datetime.date.fromisoformat(value) if value else None
    except ValueError:
        return None


def month_bounds(value):
    """'2026-03' -> (date(2026, 3, 1), date(2026, 3, 31)); None if the value isn't a valid month."""
    try:
        first = datetime.datetime.strptime(value, '%Y-%m').date()
    except (TypeError, ValueError):
        return None
    return first, first.replace(day=calendar.monthrange(first.year, first.month)[1])


def period_from_params(params):
    """Resolve the (from, to) dates: explicit dates win; a month is used only when no dates are given."""
    date_from = parse_date(params.get('date_from'))
    date_to = parse_date(params.get('date_to'))
    if not (date_from or date_to):
        bounds = month_bounds(params.get('month'))
        if bounds:
            date_from, date_to = bounds
    return date_from, date_to


def filter_project_costs(queryset, params):
    """Apply the project cost list filters (search, project, shared/direct, period).

    Shared by the on-screen list and the PDF report so both always show the same rows.
    Returns the filtered queryset and a dict describing what was applied.
    """
    project = Project.objects.filter(pk=params.get('project')).first() if params.get('project') else None
    cost_type = params.get('type') if params.get('type') in ('shared', 'direct') else ''
    q = (params.get('q') or '').strip()
    date_from, date_to = period_from_params(params)

    if project:
        queryset = queryset.filter(project=project)
    if cost_type == 'shared':
        queryset = queryset.filter(flat__isnull=True)
    elif cost_type == 'direct':
        queryset = queryset.filter(flat__isnull=False)
    if q:
        queryset = queryset.filter(
            Q(description__icontains=q) | Q(reference_no__icontains=q) | Q(supplier__name__icontains=q)
        )
    if date_from:
        queryset = queryset.filter(date__gte=date_from)
    if date_to:
        queryset = queryset.filter(date__lte=date_to)

    return queryset, {
        'project': project, 'type': cost_type, 'q': q, 'date_from': date_from, 'date_to': date_to,
    }
