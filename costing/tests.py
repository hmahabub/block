from decimal import Decimal

from django.contrib.auth.models import AnonymousUser, User
from django.test import RequestFactory, TestCase
from django.urls import reverse

from core.testing import make_account, make_project, unlock_client

from .filters import filter_project_costs
from .forms import CostCategoryForm, DirectCostForm, SharedCostForm
from .models import CostCategory, Phase, ProjectCost
from .views import ProjectCostListView, ProjectCostReportPDFView, ProjectCostUpdateView

D = Decimal


def category(name, phase=CostCategory.CategoryPhase.POST, parent=None):
    return CostCategory.objects.create(name=name, phase=phase, parent_category=parent)


class CostTestCase(TestCase):
    def setUp(self):
        self.project, self.flats = make_project()  # 4 flats
        self.account = make_account()
        self.land = category('Land', CostCategory.CategoryPhase.PRE)
        self.civil = category('Civil')
        self.admin = category('Administration', CostCategory.CategoryPhase.EITHER)

    def cost(self, cat, amount=1000, **extra):
        return ProjectCost.objects.create(
            project=self.project, cost_category=cat, date='2026-01-01', amount=amount, account=self.account, **extra,
        )


class PhaseTests(CostTestCase):
    def test_land_and_marketing_style_categories_are_pre_development(self):
        self.assertEqual(self.cost(self.land).phase, Phase.PRE)

    def test_other_categories_are_post_development(self):
        self.assertEqual(self.cost(self.civil).phase, Phase.POST)

    def test_administrative_cost_takes_the_phase_chosen_on_the_entry(self):
        self.assertEqual(self.cost(self.admin, phase=Phase.PRE).phase, Phase.PRE)
        self.assertEqual(self.cost(self.admin, phase=Phase.POST).phase, Phase.POST)

    def test_subcategories_follow_their_parent(self):
        child = category('Land Purchase', CostCategory.CategoryPhase.POST, parent=self.land)
        self.assertEqual(child.phase, CostCategory.CategoryPhase.PRE)
        self.assertEqual(self.cost(child).phase, Phase.PRE)

    def test_changing_a_parent_category_moves_its_subcategories(self):
        child = category('Sub', parent=self.civil)
        self.civil.phase = CostCategory.CategoryPhase.PRE
        self.civil.save()
        child.refresh_from_db()
        self.assertEqual(child.phase, CostCategory.CategoryPhase.PRE)

    def test_a_category_form_cannot_override_the_parents_phase(self):
        form = CostCategoryForm(data={'name': 'Sub', 'parent_category': self.land.pk, 'phase': 'POST', 'active': 'on'})
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.save().phase, CostCategory.CategoryPhase.PRE)

    def test_a_cost_on_one_flat_is_always_post_development(self):
        flat_cost = self.cost(self.land, flat=self.flats[0])
        self.assertEqual(flat_cost.phase, Phase.POST)


class SharedCostFormTests(CostTestCase):
    def data(self, cat, **extra):
        return {
            'project': self.project.pk, 'cost_category': cat.pk, 'date': '2026-01-01', 'amount': '500',
            'account': self.account.pk, **extra,
        }

    def test_shared_form_has_no_flat_field(self):
        self.assertNotIn('flat', SharedCostForm().fields)

    def test_the_account_is_required(self):
        data = self.data(self.civil)
        del data['account']
        form = SharedCostForm(data=data)
        self.assertFalse(form.is_valid())
        self.assertIn('account', form.errors)

    def test_phase_is_taken_from_the_category(self):
        form = SharedCostForm(data=self.data(self.land, phase='POST'))
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.save().phase, Phase.PRE)

    def test_administrative_cost_must_say_which_phase(self):
        form = SharedCostForm(data=self.data(self.admin))
        self.assertFalse(form.is_valid())
        self.assertIn('phase', form.errors)
        ok = SharedCostForm(data=self.data(self.admin, phase='PRE'))
        self.assertTrue(ok.is_valid(), ok.errors)
        self.assertEqual(ok.save().phase, Phase.PRE)

    def test_phase_map_tells_the_page_when_to_show_the_choice(self):
        phases = SharedCostForm().phase_map()
        self.assertEqual(phases[self.admin.pk], 'EITHER')
        self.assertEqual(phases[self.land.pk], 'PRE')

    def test_changing_a_confirmed_cost_clears_its_confirmation(self):
        cost = self.cost(self.civil)
        user = User.objects.create_user('checker')
        cost.confirm(user)
        cost.refresh_from_db()
        self.assertTrue(cost.is_confirmed)

        form = SharedCostForm(data=self.data(self.civil, amount='900'), instance=cost)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        cost.refresh_from_db()
        self.assertFalse(cost.is_confirmed)

    def test_saving_without_changes_keeps_the_confirmation(self):
        cost = self.cost(self.civil, amount=500)
        cost.confirm(User.objects.create_user('checker'))
        cost.refresh_from_db()
        form = SharedCostForm(data=self.data(self.civil), instance=cost)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        cost.refresh_from_db()
        self.assertTrue(cost.is_confirmed)


class DirectCostFormTests(CostTestCase):
    def data(self, cat, **extra):
        return {
            'flat': self.flats[0].pk, 'cost_category': cat.pk, 'date': '2026-01-01', 'amount': '700',
            'account': self.account.pk, **extra,
        }

    def test_requires_a_flat(self):
        data = self.data(self.civil)
        del data['flat']
        form = DirectCostForm(data=data)
        self.assertFalse(form.is_valid())
        self.assertIn('flat', form.errors)

    def test_pre_development_categories_are_not_offered(self):
        offered = set(DirectCostForm().fields['cost_category'].queryset)
        self.assertNotIn(self.land, offered)
        self.assertIn(self.civil, offered)
        self.assertIn(self.admin, offered)

    def test_saved_cost_belongs_to_the_flat_and_is_post_development(self):
        form = DirectCostForm(data=self.data(self.admin))
        self.assertTrue(form.is_valid(), form.errors)
        cost = form.save()
        self.assertEqual((cost.flat, cost.project, cost.phase), (self.flats[0], self.project, Phase.POST))

    def test_edit_keeps_the_original_kind(self):
        shared = self.cost(self.civil)
        direct = self.cost(self.civil, flat=self.flats[0])
        view = ProjectCostUpdateView()
        view.object = shared
        self.assertIs(view.get_form_class(), SharedCostForm)
        view.object = direct
        self.assertIs(view.get_form_class(), DirectCostForm)


class EqualSharingTests(CostTestCase):
    def test_post_development_cost_is_shared_equally_by_every_flat(self):
        self.cost(self.civil, 4000)
        self.assertEqual(self.project.cost_per_flat, 1000)
        for flat in self.flats:
            self.assertEqual(flat.shared_cost_share, 1000)

    def test_unsold_flats_carry_the_same_share_as_sold_ones(self):
        from customers.models import Customer
        from sales.models import FlatSale
        self.cost(self.civil, 4000)
        FlatSale.objects.create(
            flat=self.flats[0], customer=Customer.objects.create(name='C', phone='01711111111'),
            sale_date='2026-01-01', sale_value=1200,
        )
        self.assertEqual({f.shared_cost_share for f in self.flats}, {D(1000)})

    def test_pre_development_cost_is_not_shared_with_flat_owners(self):
        self.cost(self.land, 9000)
        self.assertEqual(self.project.cost_per_flat, 0)
        self.assertEqual((self.project.pre_development_cost, self.project.post_development_cost), (9000, 0))

    def test_direct_cost_adds_to_that_flat_only(self):
        self.cost(self.civil, 4000)
        self.cost(self.civil, 250, flat=self.flats[0])
        self.assertEqual(self.flats[0].total_cost, 1250)
        self.assertEqual(self.flats[1].total_cost, 1000)

    def test_a_shared_cost_shows_each_flats_share(self):
        shared = self.cost(self.civil, 4000)
        self.assertEqual(shared.share_per_flat, 1000)
        self.assertIsNone(self.cost(self.land, 100).share_per_flat)
        self.assertIsNone(self.cost(self.civil, 100, flat=self.flats[0]).share_per_flat)

    def test_voucher_number(self):
        cost = self.cost(self.civil)
        self.assertEqual(cost.voucher_no, f'CV-{cost.pk:05d}')


class CostListTests(CostTestCase):
    def test_list_filters_by_type(self):
        self.cost(self.civil)
        self.cost(self.civil, flat=self.flats[0])

        def listed(**params):
            view = ProjectCostListView()
            view.request = RequestFactory().get('/', params)
            view.kwargs = {}
            return [c.flat for c in view.get_queryset()]

        self.assertEqual(listed(type='shared'), [None])
        self.assertEqual(listed(type='direct'), [self.flats[0]])

    def test_list_filters_by_phase(self):
        pre, post = self.cost(self.land), self.cost(self.civil)
        queryset, applied = filter_project_costs(ProjectCost.objects.all(), {'phase': 'PRE'})
        self.assertEqual(list(queryset), [pre])
        self.assertEqual(applied['phase'], 'PRE')
        queryset, _ = filter_project_costs(ProjectCost.objects.all(), {'phase': 'POST'})
        self.assertEqual(list(queryset), [post])
        self.assertEqual(filter_project_costs(ProjectCost.objects.all(), {'phase': 'x'})[0].count(), 2)


class CostFilterAndPdfTests(CostTestCase):
    def setUp(self):
        super().setUp()
        self.user = User.objects.create_superuser('admin', 'a@example.com', 'pw')
        flat = self.flats[0]

        def make(date, cat, amount, **kw):
            return ProjectCost.objects.create(
                project=self.project, cost_category=cat, date=date, amount=amount, account=self.account, **kw)

        self.jan = make('2026-01-31', self.civil, 100)
        self.feb_start = make('2026-02-01', self.land, 200, description='Plot fee')
        self.feb_end = make('2026-02-28', self.civil, 300, flat=flat)
        self.mar = make('2026-03-01', self.civil, 400)

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
        request = RequestFactory().get('/', params)
        request.user = self.user
        return ProjectCostReportPDFView.as_view()(request)

    def test_pdf_is_generated_for_the_filtered_rows(self):
        response = self.pdf(month='2026-02')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertTrue(response.content.startswith(b'%PDF'))
        self.assertIn('2026-02-01_to_2026-02-28', response['Content-Disposition'])

    def test_pdf_filtered_by_phase_renders(self):
        self.assertTrue(self.pdf(phase='PRE').content.startswith(b'%PDF'))

    def test_pdf_with_no_matching_rows_still_renders(self):
        self.assertTrue(self.pdf(date_from='2030-01-01').content.startswith(b'%PDF'))

    def test_pdf_requires_login(self):
        request = RequestFactory().get('/')
        request.user = AnonymousUser()
        self.assertEqual(ProjectCostReportPDFView.as_view()(request).status_code, 302)

    def test_long_reports_paginate(self):
        ProjectCost.objects.bulk_create([
            ProjectCost(project=self.project, cost_category=self.civil, date='2026-04-01', amount=1,
                        description=f'Item {n}') for n in range(120)
        ])
        content = self.pdf(month='2026-04').content
        pages = content.count(b'/Type /Page') - content.count(b'/Type /Pages')
        self.assertGreater(pages, 1)


class CostingViewTests(CostTestCase):
    def test_cost_pdf_through_the_real_url(self):
        self.client.force_login(User.objects.create_superuser('admin', 'a@example.com', 'pw'))
        unlock_client(self.client)
        self.cost(self.civil)
        response = self.client.get(reverse('costing:cost-report-pdf'))
        self.assertEqual(response.status_code, 200)
