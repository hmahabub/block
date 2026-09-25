from django.contrib.auth.models import User
from django.test import RequestFactory, TestCase
from django.urls import reverse

from projects.models import Flat, Project

from .forms import DirectCostForm, SharedCostForm
from .models import CostAllocation, CostCategory, ProjectCost
from .views import ProjectCostListView, ProjectCostUpdateView


class SeparateCostEntryTests(TestCase):
    def setUp(self):
        self.client.force_login(User.objects.create_superuser('admin', 'a@example.com', 'pw'))
        self.project = Project.objects.create(project_name='P', total_saleable_area=2000)
        self.flat1 = Flat.objects.create(project=self.project, flat_no='A1', floor_no=1, saleable_area=1000, base_price=1)
        self.flat2 = Flat.objects.create(project=self.project, flat_no='A2', floor_no=1, saleable_area=500, base_price=1)
        self.category = CostCategory.objects.create(name='Civil')

    def post_cost(self, url_name, **fields):
        data = {'cost_category': self.category.pk, 'date': '2026-01-01', 'amount': '1000', **fields}
        return self.client.post(reverse(url_name), data)

    def test_shared_form_has_no_flat_field(self):
        self.assertNotIn('flat', SharedCostForm().fields)

    def test_direct_form_requires_a_flat(self):
        form = DirectCostForm(data={'cost_category': self.category.pk, 'date': '2026-01-01', 'amount': '1000'})
        self.assertFalse(form.is_valid())
        self.assertIn('flat', form.errors)

    def test_shared_cost_is_allocated_by_area(self):
        self.post_cost('costing:cost-create-shared', project=self.project.pk)
        cost = ProjectCost.objects.get()
        self.assertIsNone(cost.flat)
        self.assertTrue(cost.allocation_required)
        amounts = {a.flat_id: a.allocated_amount for a in CostAllocation.objects.all()}
        self.assertEqual(amounts[self.flat1.pk], 500)
        self.assertEqual(amounts[self.flat2.pk], 250)

    def test_direct_cost_belongs_to_one_flat_only(self):
        self.post_cost('costing:cost-create-direct', flat=self.flat1.pk)
        cost = ProjectCost.objects.get()
        self.assertEqual(cost.flat, self.flat1)
        self.assertEqual(cost.project, self.project)
        self.assertFalse(cost.allocation_required)
        self.assertEqual(CostAllocation.objects.count(), 0)
        self.assertEqual(self.flat1.direct_cost, 1000)
        self.assertEqual(self.flat2.direct_cost, 0)

    def update_form_class(self, cost):
        view = ProjectCostUpdateView()
        view.object = cost
        return view.get_form_class()

    def test_edit_keeps_the_original_kind(self):
        self.post_cost('costing:cost-create-shared', project=self.project.pk)
        self.post_cost('costing:cost-create-direct', flat=self.flat1.pk)
        shared = ProjectCost.objects.get(flat__isnull=True)
        direct = ProjectCost.objects.get(flat__isnull=False)
        self.assertIs(self.update_form_class(shared), SharedCostForm)
        self.assertIs(self.update_form_class(direct), DirectCostForm)

    def test_list_filters_by_type(self):
        self.post_cost('costing:cost-create-shared', project=self.project.pk)
        self.post_cost('costing:cost-create-direct', flat=self.flat1.pk)

        def listed(cost_type):
            view = ProjectCostListView()
            view.request = RequestFactory().get('/', {'type': cost_type})
            view.kwargs = {}
            return [c.flat for c in view.get_queryset()]

        self.assertEqual(listed('shared'), [None])
        self.assertEqual(listed('direct'), [self.flat1])

