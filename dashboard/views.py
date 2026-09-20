from django.db.models import Sum
from django.views.generic import TemplateView

from activity_log.models import ActivityLog
from costing.models import ProjectCost
from customers.models import Customer
from projects.models import Apartment, Project
from sales.models import ApartmentSale
from suppliers.models import Supplier


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
        context['apartment_count'] = Apartment.objects.count()
        context['sold_count'] = Apartment.objects.filter(status=Apartment.Status.SOLD).count()
        context['available_count'] = Apartment.objects.filter(status=Apartment.Status.AVAILABLE).count()

        total_cost = ProjectCost.objects.aggregate(total=Sum('amount'))['total'] or 0
        total_paid = ProjectCost.objects.aggregate(total=Sum('paid_amount'))['total'] or 0
        total_payable = ProjectCost.objects.aggregate(total=Sum('payable_amount'))['total'] or 0
        total_sales = ApartmentSale.objects.aggregate(total=Sum('net_sale_value'))['total'] or 0
        total_received = ApartmentSale.objects.aggregate(total=Sum('received_amount'))['total'] or 0
        total_receivable = ApartmentSale.objects.aggregate(total=Sum('receivable_amount'))['total'] or 0

        context.update({
            'total_cost': total_cost,
            'total_paid': total_paid,
            'total_payable': total_payable,
            'total_sales': total_sales,
            'total_received': total_received,
            'total_receivable': total_receivable,
            'profit': total_sales - total_cost,
        })
        return context
