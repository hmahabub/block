from decimal import Decimal

from django.contrib.auth.models import Permission, User
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import ProtectedError
from django.test import TestCase

from activity_log.models import ActivityLog
from core.testing import make_project, make_request
from customers.models import Customer
from sales.models import FlatSale

from .forms import FlatForm, GenerateFlatsForm, ProjectForm
from .models import Flat, FlatDeletionRequest, Project
from .views import (
    FlatDeletionApproveView,
    FlatDeletionRejectView,
    FlatDeletionRequestCreateView,
    FlatDeletionWithdrawView,
    GenerateFlatsView,
    ProjectDeleteView,
    build_booking_map,
)

D = Decimal


class FlatNumberingTests(TestCase):
    def setUp(self):
        self.project = Project.objects.create(project_name='P', flat_area=1700, base_price=1000, quoted_price=1200)

    def test_flat_number_is_unit_letter_plus_floor(self):
        flat = Flat.objects.create(project=self.project, unit='a', floor_no=3)
        self.assertEqual((flat.unit, flat.flat_no), ('A', 'A3'))

    def test_each_flat_gets_a_linked_parking_lot(self):
        flat = Flat.objects.create(project=self.project, unit='B', floor_no=12)
        self.assertEqual(flat.parking_lot, 'P-B12')

    def test_the_parking_lot_can_be_overridden(self):
        flat = Flat.objects.create(project=self.project, unit='B', floor_no=1, parking_lot='G-07')
        self.assertEqual(flat.parking_lot, 'G-07')

    def test_flat_form_builds_the_number_and_rejects_duplicates(self):
        data = {'unit': 'c', 'floor_no': 2, 'facing': 'South', 'parking_lot': '', 'notes': ''}
        form = FlatForm(data=data, project=self.project)
        self.assertTrue(form.is_valid(), form.errors)
        flat = form.save(commit=False)
        flat.project = self.project
        flat.save()
        self.assertEqual(flat.flat_no, 'C2')
        again = FlatForm(data=data, project=self.project)
        self.assertFalse(again.is_valid())

    def test_the_same_number_is_fine_in_another_project(self):
        other = Project.objects.create(project_name='Q')
        Flat.objects.create(project=self.project, unit='A', floor_no=1)
        form = FlatForm(data={'unit': 'A', 'floor_no': 1}, project=other)
        self.assertTrue(form.is_valid(), form.errors)

    def test_unit_must_be_one_letter(self):
        for bad in ('AB', '1', ' '):
            self.assertFalse(FlatForm(data={'unit': bad, 'floor_no': 1}, project=self.project).is_valid(), bad)

    def test_editing_a_flat_does_not_clash_with_itself(self):
        flat = Flat.objects.create(project=self.project, unit='A', floor_no=1)
        form = FlatForm(data={'unit': 'A', 'floor_no': 1, 'facing': 'East'}, instance=flat)
        self.assertTrue(form.is_valid(), form.errors)


class IdenticalFlatSpecTests(TestCase):
    def test_flats_read_type_size_and_prices_from_the_project(self):
        project, flats = make_project(
            flat_type=Project.FlatType.FOUR_BED, bedrooms=4, bathrooms=4, features='Drawing, Dining', parking_area=120,
        )
        flat = flats[0]
        self.assertEqual((flat.saleable_area, flat.base_price, flat.quoted_price, flat.parking_price), (1000, 1000, 1200, 100))
        self.assertEqual((flat.get_flat_type_display(), flat.bedrooms, flat.parking_area), ('4 Bedroom', 4, 120))
        project.base_price = 2000
        project.save()
        flat.refresh_from_db()
        self.assertEqual(flat.base_price, 2000)

    def test_total_saleable_area_is_the_per_flat_area_times_the_flat_count(self):
        project, _ = make_project(floors=3, units=2, area=1700)
        self.assertEqual(project.total_saleable_area, 6 * 1700)

    def test_flat_specs_are_not_fields_of_the_flat(self):
        names = {f.name for f in Flat._meta.get_fields()}
        for gone in ('flat_type', 'saleable_area', 'base_price', 'bedrooms', 'bathrooms', 'parking_area', 'features'):
            self.assertNotIn(gone, names)

    def test_project_form_rejects_a_quoted_price_below_the_base_price(self):
        data = {
            'project_name': 'P', 'status': 'PLANNING', 'floor_no': 1, 'land_area': 0, 'budget_amount': 0,
            'flat_type': '2BED', 'flat_area': 1000, 'base_price': 1000, 'quoted_price': 900, 'parking_price': 0,
        }
        form = ProjectForm(data=data)
        self.assertFalse(form.is_valid())
        self.assertIn('quoted_price', form.errors)
        self.assertTrue(ProjectForm(data={**data, 'quoted_price': 1000}).is_valid())


class GenerateFlatsTests(TestCase):
    def setUp(self):
        self.project = Project.objects.create(project_name='P', floor_no=12)
        self.user = User.objects.create_superuser('boss', 'b@example.com', 'pw')

    def generate(self, floors, units):
        request = make_request(self.user, '/', 'post', {'floors': floors, 'units_per_floor': units})
        return GenerateFlatsView.as_view()(request, project_pk=self.project.pk)

    def test_creates_every_unit_on_every_floor(self):
        self.assertEqual(self.generate(12, 4).status_code, 302)
        self.assertEqual(self.project.flats.count(), 48)
        numbers = set(self.project.flats.values_list('flat_no', flat=True))
        self.assertTrue({'A1', 'D1', 'A12', 'D12'} <= numbers)

    def test_running_it_again_only_adds_what_is_missing(self):
        self.generate(2, 2)
        taken = Flat.objects.get(project=self.project, flat_no='A1')
        self.generate(3, 3)
        self.assertEqual(self.project.flats.count(), 9)
        self.assertTrue(Flat.objects.filter(pk=taken.pk).exists())

    def test_the_form_limits_the_size(self):
        self.assertFalse(GenerateFlatsForm(data={'floors': 0, 'units_per_floor': 4}).is_valid())
        self.assertFalse(GenerateFlatsForm(data={'floors': 5, 'units_per_floor': 27}).is_valid())

    def test_needs_the_add_flat_permission(self):
        clerk = User.objects.create_user('clerk')
        request = make_request(clerk, '/', 'post', {'floors': 1, 'units_per_floor': 1})
        with self.assertRaises(PermissionDenied):
            GenerateFlatsView.as_view()(request, project_pk=self.project.pk)


class BookingMapTests(TestCase):
    def test_floors_run_top_down_with_one_column_per_unit(self):
        project, flats = make_project(floors=3, units=2)
        units, rows, others = build_booking_map(project)
        self.assertEqual(units, ['A', 'B'])
        self.assertEqual([floor for floor, _ in rows], [3, 2, 1])
        self.assertEqual([flat.flat_no for flat in rows[0][1]], ['A3', 'B3'])
        self.assertEqual(others, [])

    def test_booked_flats_show_their_customer(self):
        project, flats = make_project(floors=1, units=2)
        customer = Customer.objects.create(name='Rahim', phone='01711111111')
        FlatSale.objects.create(flat=flats[0], customer=customer, sale_date='2026-01-01', sale_value=1200)
        _, rows, _ = build_booking_map(project)
        booked, free = rows[0][1]
        self.assertEqual((booked.status, booked.active_sale.customer), (Flat.Status.BOOKED, customer))
        self.assertEqual((free.status, free.active_sale), (Flat.Status.AVAILABLE, None))

    def test_older_flats_without_a_unit_letter_are_kept_off_the_grid(self):
        project = Project.objects.create(project_name='Old')
        Flat.objects.create(project=project, floor_no=1, flat_no='101')
        Flat.objects.create(project=project, unit='A', floor_no=1)
        units, rows, others = build_booking_map(project)
        self.assertEqual(units, ['A'])
        self.assertEqual([f.flat_no for f in others], ['101'])


class FlatDeletionTests(TestCase):
    def setUp(self):
        self.project, self.flats = make_project()
        self.flat = self.flats[0]
        self.first = User.objects.create_superuser('first', 'f@example.com', 'pw')
        self.second = User.objects.create_superuser('second', 's@example.com', 'pw')

    def test_a_flat_cannot_be_deleted_directly(self):
        with self.assertRaises(ProtectedError), transaction.atomic():
            self.flat.delete()
        self.assertTrue(Flat.objects.filter(pk=self.flat.pk).exists())

    def test_a_project_with_flats_cannot_be_deleted(self):
        with self.assertRaises(ProtectedError):
            self.project.delete()

    def test_bulk_deleting_flats_is_blocked_too(self):
        with self.assertRaises(ProtectedError), transaction.atomic():
            Flat.objects.filter(project=self.project).delete()

    def test_one_admin_requests_and_a_different_admin_approves(self):
        request = FlatDeletionRequest.open_for(self.flat, self.first, 'Built twice')
        self.assertEqual(request.status, FlatDeletionRequest.Status.PENDING)
        self.assertTrue(Flat.objects.filter(pk=self.flat.pk).exists())
        request.approve(self.second)
        self.assertFalse(Flat.objects.filter(pk=self.flat.pk).exists())
        request.refresh_from_db()
        self.assertEqual((request.status, request.decided_by, request.flat_label), ('APPROVED', self.second, str(self.flat)))

    def test_the_requester_cannot_approve_their_own_request(self):
        request = FlatDeletionRequest.open_for(self.flat, self.first)
        with self.assertRaises(ValidationError):
            request.approve(self.first)
        self.assertTrue(Flat.objects.filter(pk=self.flat.pk).exists())

    def test_only_admins_can_request_or_approve(self):
        clerk = User.objects.create_user('clerk')
        with self.assertRaises(ValidationError):
            FlatDeletionRequest.open_for(self.flat, clerk)
        request = FlatDeletionRequest.open_for(self.flat, self.first)
        with self.assertRaises(ValidationError):
            request.approve(clerk)

    def test_a_user_with_the_delete_flat_permission_counts_as_admin(self):
        manager = User.objects.create_user('manager')
        manager.user_permissions.add(Permission.objects.get(codename='delete_flat'))
        manager = User.objects.get(pk=manager.pk)
        request = FlatDeletionRequest.open_for(self.flat, self.first)
        request.approve(manager)
        self.assertFalse(Flat.objects.filter(pk=self.flat.pk).exists())

    def test_a_flat_with_a_sale_can_never_be_deleted(self):
        customer = Customer.objects.create(name='C', phone='01711111111')
        FlatSale.objects.create(flat=self.flat, customer=customer, sale_date='2026-01-01', sale_value=1200)
        with self.assertRaises(ValidationError):
            FlatDeletionRequest.open_for(self.flat, self.first)

    def test_a_sale_made_after_the_request_blocks_the_approval(self):
        request = FlatDeletionRequest.open_for(self.flat, self.first)
        customer = Customer.objects.create(name='C', phone='01711111111')
        FlatSale.objects.create(flat=self.flat, customer=customer, sale_date='2026-01-01', sale_value=1200)
        with self.assertRaises(ValidationError):
            request.approve(self.second)
        self.assertTrue(Flat.objects.filter(pk=self.flat.pk).exists())

    def test_a_flat_with_direct_costs_cannot_be_deleted(self):
        from costing.models import CostCategory, ProjectCost
        ProjectCost.objects.create(
            project=self.project, flat=self.flat, cost_category=CostCategory.objects.create(name='C'),
            date='2026-01-01', amount=5,
        )
        self.assertEqual(self.flat.deletion_blockers(), ['it has direct cost entries'])

    def test_only_one_open_request_per_flat(self):
        FlatDeletionRequest.open_for(self.flat, self.first)
        with self.assertRaises(ValidationError):
            FlatDeletionRequest.open_for(self.flat, self.second)

    def test_rejecting_keeps_the_flat(self):
        request = FlatDeletionRequest.open_for(self.flat, self.first)
        request.reject(self.second, 'Not now')
        request.refresh_from_db()
        self.assertEqual((request.status, request.decision_note), ('REJECTED', 'Not now'))
        self.assertTrue(Flat.objects.filter(pk=self.flat.pk).exists())
        with self.assertRaises(ValidationError):
            request.approve(self.second)

    def test_only_the_requester_can_withdraw(self):
        request = FlatDeletionRequest.open_for(self.flat, self.first)
        with self.assertRaises(ValidationError):
            request.withdraw(self.second)
        request.withdraw(self.first)
        self.assertEqual(request.status, FlatDeletionRequest.Status.CANCELLED)

    def post(self, view, user, pk, **data):
        request = make_request(user, '/', 'post', data)
        return view.as_view()(request, pk=pk)

    def test_the_views_run_the_same_flow(self):
        user_request = make_request(self.first, '/', 'post', {'reason': 'Duplicate'})
        response = FlatDeletionRequestCreateView.as_view()(user_request, pk=self.flat.pk)
        self.assertEqual(response.status_code, 302)
        deletion = FlatDeletionRequest.objects.get()
        # the requester is bounced, a different admin succeeds
        self.post(FlatDeletionApproveView, self.first, deletion.pk)
        self.assertTrue(Flat.objects.filter(pk=self.flat.pk).exists())
        self.post(FlatDeletionApproveView, self.second, deletion.pk)
        self.assertFalse(Flat.objects.filter(pk=self.flat.pk).exists())
        self.assertTrue(ActivityLog.objects.filter(action='deleted', model_name='Flat').exists())

    def test_reject_and_withdraw_views(self):
        deletion = FlatDeletionRequest.open_for(self.flat, self.first)
        self.post(FlatDeletionRejectView, self.second, deletion.pk, note='no')
        deletion.refresh_from_db()
        self.assertEqual(deletion.status, 'REJECTED')
        other = FlatDeletionRequest.open_for(self.flats[1], self.first)
        self.post(FlatDeletionWithdrawView, self.first, other.pk)
        other.refresh_from_db()
        self.assertEqual(other.status, 'CANCELLED')

    def test_non_admins_cannot_open_the_request_screen(self):
        clerk = User.objects.create_user('clerk')
        with self.assertRaises(PermissionDenied):
            FlatDeletionRequestCreateView.as_view()(make_request(clerk, '/', 'get'), pk=self.flat.pk)


class ProjectDeleteViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser('boss', 'b@example.com', 'pw')

    def delete(self, project):
        return ProjectDeleteView.as_view()(make_request(self.user, '/', 'post'), pk=project.pk)

    def test_an_empty_project_is_deleted_and_logged(self):
        project = Project.objects.create(project_name='Empty')
        response = self.delete(project)
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Project.objects.filter(pk=project.pk).exists())
        log = ActivityLog.objects.get(action='deleted')
        self.assertEqual(log.model_name, 'Project')

    def test_a_project_with_flats_is_kept_with_a_message_instead_of_crashing(self):
        project, _ = make_project()
        response = self.delete(project)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Project.objects.filter(pk=project.pk).exists())
        self.assertFalse(ActivityLog.objects.filter(action='deleted').exists())


class FlatListOneProjectTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser('boss', 'b@example.com', 'pw')
        self.alpha, self.alpha_flats = make_project('Alpha', floors=1, units=2)
        self.beta, self.beta_flats = make_project('Beta', floors=1, units=3)

    def listed(self, **params):
        from .views import FlatListView
        view = FlatListView()
        view.setup(make_request(self.user, '/projects/flats/', data=params))
        return view, list(view.get_queryset())

    def test_only_one_projects_flats_are_listed(self):
        view, flats = self.listed(project=self.beta.pk)
        self.assertEqual({f.project for f in flats}, {self.beta})
        self.assertEqual(len(flats), 3)

    def test_it_opens_on_the_first_project_when_none_is_chosen(self):
        view, flats = self.listed()
        self.assertEqual(view.get_project(), self.alpha)   # first by name
        self.assertEqual({f.project for f in flats}, {self.alpha})

    def test_a_bad_project_id_falls_back_to_the_first_project(self):
        for bad in ('abc', '9999'):
            view, flats = self.listed(project=bad)
            self.assertEqual(view.get_project(), self.alpha)

    def test_search_and_status_stay_inside_the_project(self):
        _, flats = self.listed(project=self.alpha.pk, q='A1')
        self.assertEqual([f.flat_no for f in flats], ['A1'])
        _, flats = self.listed(project=self.alpha.pk, status='SOLD')
        self.assertEqual(flats, [])
