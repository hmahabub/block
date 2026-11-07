from decimal import Decimal

from django.db.models import Sum
from django.utils import timezone
from django.views.generic import TemplateView

from activity_log.models import ActivityLog
from core.reauth import money_visible
from core.workspace import current_development, in_workspace
from costing.models import Phase, ProjectCost
from customers.models import Customer
from directors.models import Director
from projects.models import Development, Flat, Project
from sales.models import FlatSale
from suppliers.models import Supplier

ZERO = Decimal('0')


def _total(queryset, field='amount'):
    return queryset.aggregate(total=Sum(field))['total'] or ZERO


class HomeView(TemplateView):
    template_name = 'home.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if not self.request.user.is_authenticated:
            return context

        request = self.request
        development = current_development(request)
        context['activity_logs'] = ActivityLog.objects.select_related('user')[:5]
        context['development_count'] = Development.objects.count()
        # shared by every project
        context['customer_count'] = Customer.objects.count()
        context['supplier_count'] = Supplier.objects.count()
        context['director_count'] = Director.objects.count()
        if development is None:
            # No figure adds up several projects: outside a project there is only the list of projects to open.
            context['developments'] = list(Development.objects.prefetch_related('buildings'))
            return context

        flats = in_workspace(Flat.objects.all(), request, 'project__development')
        context['project_count'] = in_workspace(Project.objects.all(), request, 'development').count()
        context['flat_count'] = flats.count()
        context['booked_count'] = flats.filter(status=Flat.Status.BOOKED).count()
        context['registered_count'] = flats.filter(status=Flat.Status.REGISTERED).count()
        context['sold_count'] = context['booked_count'] + context['registered_count']
        context['available_count'] = flats.filter(status=Flat.Status.AVAILABLE).count()

        # Money figures stay hidden while the sensitive screens are locked, since this page is shown to buyers.
        context['money_unlocked'] = money_visible(self.request)
        if context['money_unlocked']:
            active_sales = in_workspace(FlatSale.objects.exclude(status=FlatSale.Status.CANCELLED), request, 'project__development')
            context.update({
                'total_sales': _total(active_sales, 'sale_value'),
                'total_received': _total(active_sales, 'received_amount'),
                'total_receivable': _total(active_sales, 'receivable_amount'),
            })
            context.update(self.cost_stats(timezone.localdate(), context['flat_count'], request))
        return context

    @staticmethod
    def cost_stats(today, flat_count, request):
        costs = in_workspace(ProjectCost.objects.all(), request, 'project__development')
        post_shared = _total(costs.filter(phase=Phase.POST, flat__isnull=True))

        top_heads = {}
        for cost in costs.select_related('cost_category', 'cost_category__parent_category'):
            head = (cost.cost_category.parent_category or cost.cost_category).name
            top_heads[head] = top_heads.get(head, ZERO) + cost.amount

        return {
            'total_cost': _total(costs),
            'pre_cost': _total(costs.filter(phase=Phase.PRE)),
            'post_cost': _total(costs.filter(phase=Phase.POST)),
            'month_cost': _total(costs.filter(date__year=today.year, date__month=today.month)),
            'cost_per_flat': post_shared / flat_count if flat_count else ZERO,
            'top_cost_heads': sorted(top_heads.items(), key=lambda item: -item[1])[:5],
        }
