import io
import time
from decimal import Decimal

from django.contrib.auth.models import Group, Permission, User
from django.db import transaction
from django.http import HttpResponse
from django.test import RequestFactory, TestCase
from openpyxl import load_workbook

from books.ledger import assign_account, confirm_entries
from core.testing import make_account, make_project, make_request
from costing.models import CostCategory, ProjectCost
from customers.models import Customer
from projects.models import Development, Project
from sales.models import CustomerPayment, FlatSale
from sms.models import SmsLog

from .context import acting_as
from .middleware import AuditContextMiddleware
from .models import ActivityLog
from .views import AuditTrailView

D = Decimal
UNLOCKED = dict(session={'reauth_until': time.time() + 600, 'reauth_token': 'tok'}, cookies={'daj_unlocked': 'tok'})


class AuditTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser('boss', 'b@example.com', 'pw')
        self.other = User.objects.create_user('clerk')

    def logs(self, **filters):
        return ActivityLog.objects.filter(**filters).order_by('id')

    def last(self, **filters):
        return self.logs(**filters).last()


class CreateUpdateDeleteTests(AuditTestCase):
    def test_a_create_is_recorded_with_who_what_and_the_new_values(self):
        with acting_as(self.user, '10.0.0.5'):
            customer = Customer.objects.create(name='Rahim', phone='01711000001', tin='123456789012')
        log = self.last(model_name='Customer')
        self.assertEqual((log.action, log.user, log.app_label, log.object_id, log.ip_address), ('created', self.user, 'customers', str(customer.pk), '10.0.0.5'))
        self.assertIn('Rahim', log.object_repr)
        self.assertEqual(log.changes['name'], [None, 'Rahim'])
        self.assertEqual(log.changes['tin'], [None, '123456789012'])
        self.assertEqual(log.changes['phone'], [None, '+8801711000001'])    # the value actually stored

    def test_an_update_records_only_what_changed_old_and_new(self):
        customer = Customer.objects.create(name='Rahim', phone='01711000001')
        with acting_as(self.user):
            customer.name = 'Rahim Uddin'
            customer.occupation = 'Engineer'
            customer.save()
        log = self.last(action='updated', model_name='Customer')
        self.assertEqual(log.changes, {'name': ['Rahim', 'Rahim Uddin'], 'occupation': ['', 'Engineer']})
        self.assertEqual(log.user, self.user)

    def test_saving_without_a_real_change_records_nothing(self):
        customer = Customer.objects.create(name='Rahim', phone='01711000001')
        before = ActivityLog.objects.count()
        customer.save()
        customer.save()
        self.assertEqual(ActivityLog.objects.count(), before)

    def test_amounts_and_dates_compare_by_value_not_by_how_they_were_typed(self):
        investment, _ = make_project()
        account = make_account()
        category = CostCategory.objects.create(name='Civil')
        cost = ProjectCost.objects.create(project=investment, cost_category=category, date='2026-01-01', amount=100, account=account)
        before = ActivityLog.objects.count()
        cost.amount = D('100.00')         # same money, different spelling
        cost.date = '2026-01-01'          # same day, as text
        cost.save()
        self.assertEqual(ActivityLog.objects.count(), before)
        cost.amount = D('150.50')
        cost.save()
        self.assertEqual(self.last(action='updated', model_name='ProjectCost').changes, {'amount': ['100', '150.5']})

    def test_a_delete_keeps_a_snapshot_of_what_was_removed(self):
        customer = Customer.objects.create(name='Rahim', phone='01711000001', occupation='Engineer')
        pk = customer.pk
        with acting_as(self.user):
            customer.delete()
        log = self.last(action='deleted', model_name='Customer')
        self.assertEqual((log.object_id, log.user), (str(pk), self.user))
        self.assertIn('Rahim', log.object_repr)
        self.assertEqual(log.changes['occupation'], ['Engineer', None])
        self.assertEqual(log.changes['name'], ['Rahim', None])

    def test_deleting_a_parent_also_records_the_children_that_went_with_it(self):
        project = Project.objects.create(project_name='Empty Tower')
        category = CostCategory.objects.create(name='Civil')
        ProjectCost.objects.create(project=project, cost_category=category, date='2026-01-01', amount=5)
        project.delete()
        self.assertTrue(self.logs(action='deleted', model_name='ProjectCost').exists())
        self.assertTrue(self.logs(action='deleted', model_name='Project').exists())

    def test_every_business_record_type_is_tracked(self):
        project, flats = make_project()
        customer = Customer.objects.create(name='C', phone='01711000002')
        FlatSale.objects.create(flat=flats[0], customer=customer, sale_date='2026-01-01', sale_value=1200)
        seen = set(ActivityLog.objects.values_list('model_name', flat=True))
        for expected in ('Project', 'Flat', 'Customer', 'FlatSale'):
            self.assertIn(expected, seen)

    def test_a_rolled_back_change_leaves_no_trail(self):
        before = ActivityLog.objects.count()
        try:
            with transaction.atomic():
                Customer.objects.create(name='Ghost', phone='01711000003')
                raise RuntimeError('undo')
        except RuntimeError:
            pass
        self.assertEqual(ActivityLog.objects.count(), before)

    def test_without_a_request_the_change_is_attributed_to_the_system(self):
        Customer.objects.create(name='Scripted', phone='01711000004')
        log = self.last(model_name='Customer')
        self.assertIsNone(log.user)
        self.assertIsNone(log.ip_address)


class WhatIsNotTrackedTests(AuditTestCase):
    def test_system_bookkeeping_is_left_out(self):
        from core.models import Sequence
        before = ActivityLog.objects.count()
        Sequence.objects.create(key='scratch', last_number=3)
        customer = Customer.objects.create(name='C', phone='01711000005')
        SmsLog.objects.create(customer=customer, phone='+8801711000005', kind='PAYMENT', message='hi', status='LOGGED')
        names = set(ActivityLog.objects.exclude(id__lte=0).values_list('model_name', flat=True))
        self.assertNotIn('Sequence', names)
        self.assertNotIn('SmsLog', names)
        self.assertNotIn('ActivityLog', names)
        self.assertGreater(ActivityLog.objects.count(), before)   # the customer itself was recorded

    def test_the_trail_does_not_record_itself(self):
        Customer.objects.create(name='C', phone='01711000006')
        self.assertFalse(ActivityLog.objects.filter(model_name='ActivityLog').exists())


class UserAccountTests(AuditTestCase):
    def test_a_password_change_is_recorded_but_never_the_password(self):
        user = User.objects.create_user('newbie', password='first-pass')
        with acting_as(self.user):
            user.set_password('second-pass')
            user.save()
        log = self.last(action='updated', model_name='User', object_id=str(user.pk))
        self.assertEqual(log.changes['password'], ['(changed)', '(changed)'])
        raw = str(ActivityLog.objects.filter(model_name='User').values_list('changes', flat=True))
        self.assertNotIn('pbkdf2', raw)
        self.assertNotIn('first-pass', raw)

    def test_logging_in_alone_is_not_an_event(self):
        user = User.objects.create_user('walker', password='pw')
        before = ActivityLog.objects.count()
        user.last_login = user.date_joined
        user.save(update_fields=['last_login'])
        self.assertEqual(ActivityLog.objects.count(), before)

    def test_giving_a_user_a_group_or_permission_is_recorded(self):
        group = Group.objects.create(name='Accountants')
        user = User.objects.create_user('acct')
        with acting_as(self.user):
            user.groups.add(group)
            user.user_permissions.add(Permission.objects.get(codename='confirm_entries'))
        logs = self.logs(action='updated', model_name='User', object_id=str(user.pk))
        fields = [next(iter(log.changes)) for log in logs]
        self.assertIn('groups', fields)
        self.assertIn('user_permissions', fields)
        self.assertEqual(logs.get(changes__groups__isnull=False).changes['groups'], [None, [group.pk]])


class BypassPathsTests(AuditTestCase):
    """The few changes made with a queryset .update() (no signals) are logged explicitly."""

    def setUp(self):
        super().setUp()
        self.project, self.flats = make_project()
        self.account = make_account('Bank 1', opening_balance=10_000)
        self.customer = Customer.objects.create(name='C', phone='01711000007')
        self.sale = FlatSale.objects.create(flat=self.flats[0], customer=self.customer, sale_date='2026-01-01', sale_value=1200)

    def test_a_payment_logs_itself_and_the_sale_totals_it_changed(self):
        with acting_as(self.user):
            payment = CustomerPayment.objects.create(sale=self.sale, payment_date='2026-02-01', amount=500, account=self.account)
        self.assertTrue(self.logs(action='created', model_name='CustomerPayment', object_id=str(payment.pk)).exists())
        sale_log = self.last(action='updated', model_name='FlatSale')
        self.assertEqual(sale_log.user, self.user)
        self.assertEqual(sale_log.changes['received_amount'], ['0', '500'])
        self.assertEqual(sale_log.changes['receivable_amount'], ['1200', '700'])

    def test_confirming_a_book_entry_is_recorded(self):
        payment = CustomerPayment.objects.create(sale=self.sale, payment_date='2026-02-01', amount=500, account=self.account)
        confirm_entries([f'cp:{payment.pk}'], self.user)
        log = self.last(action='updated', model_name='CustomerPayment', object_id=str(payment.pk))
        self.assertEqual(log.user, self.user)
        self.assertIsNone(log.changes['confirmed_at'][0])
        self.assertIsNotNone(log.changes['confirmed_at'][1])
        self.assertEqual(log.changes['confirmed_by'], [None, self.user.pk])

    def test_a_refused_confirmation_leaves_no_confirmation_in_the_trail(self):
        category = CostCategory.objects.create(name='Civil')
        cost = ProjectCost.objects.create(project=self.project, cost_category=category, date='2026-01-05', amount=999_999, account=self.account)
        done, problems = confirm_entries([f'pc:{cost.pk}'], self.user)
        self.assertEqual(done, [])
        self.assertFalse(self.logs(action='updated', model_name='ProjectCost', object_id=str(cost.pk), changes__has_key='confirmed_at').exists())

    def test_giving_an_old_record_an_account_is_recorded(self):
        old = CustomerPayment.objects.create(sale=self.sale, payment_date='2026-02-01', amount=50)
        assign_account([f'cp:{old.pk}'], self.account)
        log = self.last(action='updated', model_name='CustomerPayment', object_id=str(old.pk))
        self.assertEqual(log.changes['account'], [None, self.account.pk])

    def test_moving_a_category_to_another_phase_records_its_sub_categories(self):
        parent = CostCategory.objects.create(name='Land', phase='PRE')
        child = CostCategory.objects.create(name='Registration', parent_category=parent)
        parent.phase = 'POST'
        parent.save()
        self.assertTrue(self.logs(action='updated', model_name='CostCategory', object_id=str(child.pk)).exists())


class ThroughTheScreensTests(AuditTestCase):
    def test_the_middleware_attributes_changes_to_the_logged_in_user_and_their_ip(self):
        def view(request):
            Customer.objects.create(name='Via request', phone='01711000008')
            return HttpResponse('ok')

        request = RequestFactory().get('/', REMOTE_ADDR='192.168.1.20')
        request.user = self.user
        AuditContextMiddleware(view)(request)
        log = self.last(model_name='Customer')
        self.assertEqual((log.user, log.ip_address), (self.user, '192.168.1.20'))

    def test_the_forwarded_address_wins_behind_a_proxy(self):
        def view(request):
            Customer.objects.create(name='Proxied', phone='01711000009')
            return HttpResponse('ok')

        request = RequestFactory().get('/', REMOTE_ADDR='10.0.0.1', HTTP_X_FORWARDED_FOR='203.0.113.9, 10.0.0.1')
        request.user = self.user
        AuditContextMiddleware(view)(request)
        self.assertEqual(self.last(model_name='Customer').ip_address, '203.0.113.9')

    def test_the_user_is_forgotten_after_the_request(self):
        request = RequestFactory().get('/')
        request.user = self.user
        AuditContextMiddleware(lambda r: HttpResponse('ok'))(request)
        Customer.objects.create(name='Later', phone='01711000010')
        self.assertIsNone(self.last(model_name='Customer').user)

    def test_a_form_create_is_recorded_once_not_twice(self):
        from customers.views import CustomerCreateView
        request = make_request(self.user, '/', 'post', {'name': 'Form Customer', 'phone': '01711000011', 'nationality': 'Bangladeshi', 'sms_enabled': 'on'})
        AuditContextMiddleware(lambda r: CustomerCreateView.as_view()(r))(request)
        self.assertEqual(self.logs(action='created', model_name='Customer').count(), 1)
        self.assertEqual(self.last(model_name='Customer').user, self.user)

    def test_a_form_delete_is_recorded_once_with_the_user(self):
        from projects.views import ProjectDeleteView
        project = Project.objects.create(project_name='Short Lived')
        request = make_request(self.user, '/', 'post')
        AuditContextMiddleware(lambda r: ProjectDeleteView.as_view()(r, pk=project.pk))(request)
        logs = self.logs(action='deleted', model_name='Project')
        self.assertEqual((logs.count(), logs.last().user), (1, self.user))

    def test_buildings_and_projects_are_named_the_way_the_screens_name_them(self):
        building = Project.objects.create(project_name='Tower')
        development = Development.objects.create(name='Estate')
        self.assertEqual(self.last(model_name='Project', object_id=str(building.pk)).model_label, 'Building')
        self.assertEqual(self.last(model_name='Development', object_id=str(development.pk)).model_label, 'Project')

    def test_changes_read_with_the_field_labels_people_see(self):
        customer = Customer.objects.create(name='A', phone='01711000012')
        customer.identification_no = '999'
        customer.save()
        rows = self.last(action='updated', model_name='Customer').change_rows()
        self.assertEqual(rows, [('NID / Passport No.', '', '999')])


class ImmutabilityTests(AuditTestCase):
    def test_an_entry_cannot_be_edited(self):
        Customer.objects.create(name='A', phone='01711000013')
        log = ActivityLog.objects.first()
        log.object_repr = 'tampered'
        with self.assertRaises(PermissionError):
            log.save()

    def test_an_entry_cannot_be_deleted(self):
        Customer.objects.create(name='A', phone='01711000014')
        with self.assertRaises(PermissionError):
            ActivityLog.objects.first().delete()

    def test_the_admin_site_cannot_add_change_or_delete_entries(self):
        from django.contrib import admin
        model_admin = admin.site._registry[ActivityLog]
        request = make_request(self.user)
        self.assertFalse(model_admin.has_add_permission(request))
        self.assertFalse(model_admin.has_change_permission(request))
        self.assertFalse(model_admin.has_delete_permission(request))

    def test_deleting_a_user_keeps_what_they_did_but_blanks_who(self):
        worker = User.objects.create_user('worker')
        with acting_as(worker):
            Customer.objects.create(name='Made by worker', phone='01711000015')
        worker.delete()
        log = self.last(action='created', model_name='Customer')
        self.assertIsNone(log.user)
        self.assertIn('Made by worker', log.object_repr)


class AuditScreenTests(AuditTestCase):
    def setUp(self):
        super().setUp()
        with acting_as(self.user, '10.0.0.1'):
            self.rahim = Customer.objects.create(name='Rahim', phone='01711000021')
            self.rahim.occupation = 'Engineer'
            self.rahim.save()
        with acting_as(self.other, '10.0.0.2'):
            self.karim = Customer.objects.create(name='Karim', phone='01711000022')
            Project.objects.create(project_name='Tower')
            self.karim.delete()

    def view(self, **params):
        view = AuditTrailView()
        view.setup(make_request(self.user, '/activity-log/', data=params, **UNLOCKED))
        return view

    def shown(self, **params):
        return list(self.view(**params).filtered())

    def test_the_page_renders_with_expandable_old_and_new_values(self):
        response = AuditTrailView.as_view()(make_request(self.user, '/', **UNLOCKED))
        response.render()
        html = response.content.decode()
        for expected in ('Audit trail', 'Rahim', 'Engineer', 'Created', 'Updated', 'Deleted', '10.0.0.1', 'history of this record'):
            self.assertIn(expected, html)

    def test_filter_by_user(self):
        self.assertEqual({log.user for log in self.shown(user=self.other.pk)}, {self.other})
        self.assertTrue(all(log.user is None for log in self.shown(user='system')))

    def test_filter_by_action(self):
        self.assertEqual({log.action for log in self.shown(action='deleted')}, {'deleted'})
        self.assertEqual(len(self.shown(action='nonsense')), len(self.shown()))

    def test_filter_by_record_type(self):
        self.assertEqual({log.model_name for log in self.shown(type='customers.Customer')}, {'Customer'})
        self.assertEqual({log.model_name for log in self.shown(type='projects.Project')}, {'Project'})

    def test_search(self):
        self.assertEqual({log.object_repr.split(' (')[0] for log in self.shown(q='Rahim')}, {'Rahim'})
        self.assertTrue(self.shown(q='clerk'))     # by user name

    def test_the_history_of_one_record(self):
        logs = self.shown(app='customers', model='Customer', object=self.rahim.pk)
        self.assertEqual([log.action for log in reversed(logs)], ['created', 'updated'])

    def test_date_range(self):
        self.assertEqual(self.shown(date_from='2999-01-01'), [])
        self.assertEqual(self.shown(date_to='2000-01-01'), [])
        self.assertTrue(self.shown(date_from='2000-01-01', date_to='2999-12-31'))
        self.assertTrue(self.shown(date_from='garbage'))

    def test_newest_first(self):
        stamps = [log.created_at for log in self.shown()]
        self.assertEqual(stamps, sorted(stamps, reverse=True))

    def test_excel_download(self):
        request = make_request(self.user, '/', data={'format': 'xlsx', 'type': 'customers.Customer'}, **UNLOCKED)
        response = AuditTrailView.as_view()(request)
        self.assertIn('spreadsheetml', response['Content-Type'])
        sheet = load_workbook(io.BytesIO(response.content)).active
        cells = [c.value for row in sheet.iter_rows() for c in row]
        self.assertIn('Rahim', ' '.join(str(c) for c in cells))
        self.assertTrue(any('Occupation:  -> Engineer' in str(c) or 'Occupation' in str(c) for c in cells))
        self.assertIn('10.0.0.1', cells)

    def test_it_needs_a_login(self):
        from django.contrib.auth.models import AnonymousUser
        request = RequestFactory().get('/')
        request.user = AnonymousUser()
        self.assertEqual(AuditTrailView.as_view()(request).status_code, 302)

    def test_it_sits_behind_the_password_prompt(self):
        from django.conf import settings
        from django.urls import resolve
        from core import reauth
        self.assertIn('activity_log', settings.SENSITIVE_NAMESPACES)
        request = make_request(self.user, '/activity-log/')
        request.resolver_match = resolve('/activity-log/')
        response = reauth.ReauthMiddleware(lambda r: None).process_view(request, None, (), {})
        self.assertEqual(response.status_code, 302)
        self.assertIn('/confirm-password/', response['Location'])

    def test_pagination(self):
        for n in range(60):
            Customer.objects.create(name=f'Bulk {n}', phone=f'0171199{n:04d}')
        response = AuditTrailView.as_view()(make_request(self.user, '/', **UNLOCKED))
        self.assertEqual(len(response.context_data['logs']), 50)
        self.assertTrue(response.context_data['is_paginated'])
