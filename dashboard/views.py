from decimal import Decimal

from django.conf import settings
from django.db.models import Sum
from django.utils import timezone
from django.views.generic import TemplateView

from activity_log.models import ActivityLog
from core.reauth import is_unlocked
from costing.models import Phase, ProjectCost
from customers.models import Customer
from projects.models import Flat, Project
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

        context['activity_logs'] = ActivityLog.objects.select_related('user')[:5]
        context['project_count'] = Project.objects.count()
        context['customer_count'] = Customer.objects.count()
        context['supplier_count'] = Supplier.objects.count()
        context['flat_count'] = Flat.objects.count()
        context['sold_count'] = Flat.objects.filter(status=Flat.Status.SOLD).count()
        context['booked_count'] = Flat.objects.filter(status=Flat.Status.BOOKED).count()
        context['available_count'] = Flat.objects.filter(status=Flat.Status.AVAILABLE).count()

        active_sales = FlatSale.objects.exclude(status=FlatSale.Status.CANCELLED)
        context.update({
            'total_sales': _total(active_sales, 'sale_value'),
            'total_received': _total(active_sales, 'received_amount'),
            'total_receivable': _total(active_sales, 'receivable_amount'),
        })

        # Cost figures stay hidden while Costing is locked, since this page is shown to buyers.
        context['costs_unlocked'] = 'costing' not in settings.SENSITIVE_NAMESPACES or is_unlocked(self.request)
        if context['costs_unlocked']:
            context.update(self.cost_stats(timezone.localdate(), context['flat_count']))
        return context

    @staticmethod
    def cost_stats(today, flat_count):
        costs = ProjectCost.objects.all()
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
