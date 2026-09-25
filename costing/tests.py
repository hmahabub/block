from django.contrib.auth.models import User
from django.test import RequestFactory, TestCase
from django.urls import reverse

from projects.models import Flat, Project

from .forms import DirectCostForm, SharedCostForm
from .models import CostAllocation, CostCategory, ProjectCost
from .filters import filter_project_costs
from .views import ProjectCostListView, ProjectCostReportPDFView, ProjectCostUpdateView


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



class CostFilterAndPdfTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser('admin', 'a@example.com', 'pw')
        self.project = Project.objects.create(project_name='Alpha', total_saleable_area=1000)
        self.flat = Flat.objects.create(project=self.project, flat_no='A1', floor_no=1, saleable_area=1000, base_price=1)
        civil = CostCategory.objects.create(name='Civil')
        land = CostCategory.objects.create(name='Land')
        make = lambda date, category, amount, **kw: ProjectCost.objects.create(
            project=self.project, cost_category=category, date=date, amount=amount, **kw)
        self.jan = make('2026-01-31', civil, 100)
        self.feb_start = make('2026-02-01', land, 200, description='Plot fee')
        self.feb_end = make('2026-02-28', civil, 300, flat=self.flat)
        self.mar = make('2026-03-01', civil, 400)

    def ids(self, **params):
        queryset, _ = filter_project_costs(ProjectCost.objects.all(), params)
        return {c.pk for c in queryset}

    def test_month_filter_includes_first_and_last_day(self):
        self.assertEqual(self.ids(month='2026-02'), {self.feb_start.pk, self.feb_end.pk})

    def test_date_range_is_inclusive(self):
        self.assertEqual(self.ids(date_from='2026-01-31', date_to='2026-02-01'), {self.jan.pk, self.feb_start.pk})

    def test_open_ended_ranges(self):
        self.assertEqual(self.ids(date_from='2026-03-01'), {self.mar.pk})
        self.assertEqual(self.ids(date_to='2026-01-31'), {self.jan.pk})

    def test_explicit_dates_win_over_month(self):
        self.assertEqual(self.ids(month='2026-02', date_from='2026-03-01', date_to='2026-03-31'), {self.mar.pk})

    def test_february_bounds_handle_month_length(self):
        from .filters import month_bounds
        self.assertEqual(str(month_bounds('2026-02')[1]), '2026-02-28')
        self.assertEqual(str(month_bounds('2028-02')[1]), '2028-02-29')

    def test_bad_input_is_ignored_not_an_error(self):
        self.assertEqual(len(self.ids(month='nonsense', date_from='31/12/2026')), 4)

    def test_filters_combine(self):
        self.assertEqual(self.ids(month='2026-02', type='direct'), {self.feb_end.pk})
        self.assertEqual(self.ids(month='2026-02', q='Plot'), {self.feb_start.pk})

    def pdf(self, **params):
        view = ProjectCostReportPDFView.as_view()
        request = RequestFactory().get('/', params)
        request.user = self.user
        return view(request)

    def test_pdf_is_generated_for_the_filtered_rows(self):
        response = self.pdf(month='2026-02')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertTrue(response.content.startswith(b'%PDF'))
        self.assertIn('2026-02-01_to_2026-02-28', response['Content-Disposition'])

    def test_pdf_with_no_matching_rows_still_renders(self):
        response = self.pdf(date_from='2030-01-01')
        self.assertTrue(response.content.startswith(b'%PDF'))

    def test_pdf_requires_login(self):
        from django.contrib.auth.models import AnonymousUser
        request = RequestFactory().get('/')
        request.user = AnonymousUser()
        self.assertEqual(ProjectCostReportPDFView.as_view()(request).status_code, 302)

    def test_long_reports_paginate(self):
        civil = CostCategory.objects.get(name='Civil')
        ProjectCost.objects.bulk_create([
            ProjectCost(project=self.project, cost_category=civil, date='2026-04-01', amount=1,
                        description=f'Item {n}') for n in range(120)
        ])
        content = self.pdf(month='2026-04').content
        pages = content.count(b'/Type /Page') - content.count(b'/Type /Pages')
        self.assertGreater(pages, 1)
