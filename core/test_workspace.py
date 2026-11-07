"""Working inside one project: every screen shows only that project's records."""
import re
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from books.ledger import account_summaries, collect_entries, pending_count
from costing.models import CostCategory, ProjectCost
from customers.models import Customer
from directors.models import Director, DirectorTransaction
from projects.models import Development, Flat, Project
from sales.models import CustomerPayment, FlatSale
from suppliers.models import Supplier

from .testing import make_account, make_project, unlock_client
from .workspace import SESSION_KEY

D = Decimal


class WorkspaceTestCase(TestCase):
    """Two projects, each with a building, a flat, a sale, a payment, a cost and a director investment."""

    def setUp(self):
        self.user = User.objects.create_superuser('boss', 'b@example.com', 'pw')
        self.client.force_login(self.user)
        unlock_client(self.client)
        self.bank = make_account('Bank 1')
        self.category = CostCategory.objects.create(name='Civil')
        self.director = Director.objects.create(name='Rahim', phone='01711000001')
        self.a = self.build('Alpha', 'Tower A')
        self.b = self.build('Beta', 'Tower B')

    def build(self, development_name, building_name):
        development = Development.objects.create(name=development_name)
        building, flats = make_project(building_name, floors=1, units=2, development=development)
        customer = Customer.objects.create(name=f'Buyer of {building_name}', phone=f'017110001{len(Customer.objects.all()):02d}')
        sale = FlatSale.objects.create(flat=flats[0], customer=customer, sale_date='2026-01-01', sale_value=1500)
        payment = CustomerPayment.objects.create(sale=sale, payment_date='2026-01-05', amount=500, account=self.bank)
        supplier = Supplier.objects.create(name=f'Supplier of {building_name}')
        cost = ProjectCost.objects.create(
            project=building, cost_category=self.category, date='2026-01-06', amount=200, account=self.bank, supplier=supplier,
        )
        invest = DirectorTransaction.objects.create(
            director=self.director, development=development, kind='INVESTMENT', date='2026-01-02', amount=1000, account=self.bank,
        )
        return type('Set', (), dict(
            development=development, building=building, flats=flats, customer=customer, sale=sale, payment=payment,
            supplier=supplier, cost=cost, invest=invest,
        ))

    def enter(self, development):
        response = self.client.post(reverse('enter-project', args=[development.pk]))
        self.assertEqual(response.status_code, 302)

    def text(self, name, *args, **query):
        response = self.client.get(reverse(name, args=args), query)
        self.assertEqual(response.status_code, 200, name)
        # the bar under the menu lists every project, so leave it out when checking what the page itself shows
        return re.sub(r'<li[^>]*id="workspace-bar".*?\n</li>', '', response.content.decode(), flags=re.S)


class EnterAndExitTests(WorkspaceTestCase):
    def test_entering_a_project_is_remembered_in_the_session(self):
        self.enter(self.a.development)
        self.assertEqual(self.client.session[SESSION_KEY], self.a.development.pk)
        self.assertIn('workspace-bar', self.client.get(reverse('home')).content.decode())

    def test_exit_goes_back_to_every_project(self):
        self.enter(self.a.development)
        self.client.post(reverse('exit-project'))
        self.assertNotIn(SESSION_KEY, self.client.session)
        self.assertNotIn('workspace-bar', self.client.get(reverse('home')).content.decode())

    def test_entering_needs_a_post_and_a_real_project(self):
        self.assertEqual(self.client.get(reverse('enter-project', args=[self.a.development.pk])).status_code, 405)
        self.assertEqual(self.client.post(reverse('enter-project', args=[9999])).status_code, 404)

    def test_visitors_cannot_enter(self):
        self.client.logout()
        self.assertEqual(self.client.post(reverse('enter-project', args=[self.a.development.pk])).status_code, 302)
        self.assertNotIn(SESSION_KEY, self.client.session)

    def test_a_project_deleted_while_inside_it_just_ends_the_visit(self):
        empty = Development.objects.create(name='Empty')
        self.enter(empty)
        empty.delete()
        self.assertEqual(self.client.get(reverse('home')).status_code, 200)
        self.assertNotIn(SESSION_KEY, self.client.session)

    def test_the_home_page_offers_every_project_until_one_is_opened(self):
        page = self.text('home')
        self.assertIn('Open a project', page)
        self.assertIn('Alpha', page)
        self.assertIn('Beta', page)

    def test_the_bar_lets_you_switch_project(self):
        self.enter(self.a.development)
        page = self.client.get(reverse('projects:list')).content.decode()
        self.assertIn(reverse('enter-project', args=[self.b.development.pk]), page)
        self.assertIn(reverse('exit-project'), page)


class OutsideAProjectTests(WorkspaceTestCase):
    """Customers, suppliers and directors are shared; everything else needs a project, so nothing adds up projects."""

    PROJECT_SCREENS = (
        'projects:list', 'projects:flat-list', 'costing:cost-list', 'costing:budget-list', 'costing:cost-create-shared',
        'sales:list', 'sales:payment-list', 'sales:create', 'books:book', 'books:to-confirm', 'reports:index',
        'reports:finance', 'reports:dues', 'sms:reminders', 'projects:deletion-requests',
    )

    def test_the_per_project_screens_ask_you_to_open_a_project_first(self):
        for name in self.PROJECT_SCREENS:
            response = self.client.get(reverse(name), follow=True)
            self.assertEqual(response.redirect_chain[-1][0], reverse('home'), name)
            self.assertContains(response, 'Open a project first', msg_prefix=name)

    def test_a_record_cannot_be_opened_by_its_address_without_a_project(self):
        for name, obj in (('costing:cost-detail', self.a.cost), ('sales:detail', self.a.sale), ('projects:detail', self.a.building),
                          ('projects:flat-detail', self.a.flats[0]), ('sales:payment-receipt', self.a.payment)):
            response = self.client.get(reverse(name, args=[obj.pk]))
            self.assertRedirects(response, reverse('home'), msg_prefix=name)

    def test_posting_without_a_project_changes_nothing(self):
        response = self.client.post(reverse('costing:cost-delete', args=[self.a.cost.pk]))
        self.assertRedirects(response, reverse('home'))
        self.assertTrue(ProjectCost.objects.filter(pk=self.a.cost.pk).exists())

    def test_the_shared_screens_stay_open(self):
        for name in ('home', 'projects:development-list', 'customers:list', 'suppliers:list', 'directors:list',
                     'directors:summary', 'costing:category-list', 'sales:reference-list', 'books:accounts',
                     'books:transfers', 'sms:log'):
            self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)

    def test_customers_suppliers_and_directors_show_every_project(self):
        self.assertIn('Buyer of Tower A', self.text('customers:list'))
        self.assertIn('Buyer of Tower B', self.text('customers:list'))
        self.assertIn('Supplier of Tower A', self.text('suppliers:list'))
        self.assertIn('Supplier of Tower B', self.text('suppliers:list'))
        page = self.text('directors:detail', self.director.pk)
        self.assertIn('Alpha', page)
        self.assertIn('Beta', page)

    def test_the_home_page_has_no_combined_figures(self):
        response = self.client.get(reverse('home'))
        for key in ('flat_count', 'sold_count', 'total_sales', 'total_received', 'total_cost', 'project_count'):
            self.assertNotIn(key, response.context, key)
        self.assertEqual((response.context['customer_count'], response.context['supplier_count']), (2, 2))
        self.assertEqual(response.context['director_count'], 1)

    def test_the_account_list_shows_no_money_without_a_project(self):
        page = self.text('books:accounts')
        self.assertIn('Bank 1', page)
        self.assertNotIn('Opening', page)
        self.assertNotIn('To confirm', page)

    def test_the_public_invoice_link_still_works(self):
        from sms.whatsapp import invoice_url

        request = self.client.get('/').wsgi_request
        link = invoice_url(request, self.a.sale)
        self.client.logout()
        self.assertEqual(self.client.get(link).status_code, 200)


class OnlyTheProjectsRecordsShowTests(WorkspaceTestCase):
    def setUp(self):
        super().setUp()
        self.enter(self.a.development)

    def test_buildings(self):
        page = self.text('projects:list')
        self.assertIn('Tower A', page)
        self.assertNotIn('Tower B', page)

    def test_a_building_of_another_project_cannot_be_opened(self):
        self.assertEqual(self.client.get(reverse('projects:detail', args=[self.b.building.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse('projects:detail', args=[self.a.building.pk])).status_code, 200)

    def test_flats(self):
        page = self.text('projects:flat-list', project=self.b.building.pk)  # asking for the other project's building
        self.assertNotIn('Tower B', page)
        self.assertEqual(self.client.get(reverse('projects:flat-detail', args=[self.b.flats[0].pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse('projects:flat-detail', args=[self.a.flats[0].pk])).status_code, 200)

    def test_flats_cannot_be_added_to_another_projects_building(self):
        self.assertEqual(self.client.get(reverse('projects:flat-create', args=[self.b.building.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse('projects:flat-generate', args=[self.b.building.pk])).status_code, 404)

    def test_costs(self):
        page = self.text('costing:cost-list')
        self.assertIn(reverse('costing:cost-detail', args=[self.a.cost.pk]), page)
        self.assertNotIn(reverse('costing:cost-detail', args=[self.b.cost.pk]), page)
        self.assertEqual(self.client.get(reverse('costing:cost-detail', args=[self.b.cost.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse('costing:cost-voucher', args=[self.b.cost.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse('costing:cost-update', args=[self.b.cost.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse('costing:cost-delete', args=[self.b.cost.pk])).status_code, 404)
        self.assertTrue(ProjectCost.objects.filter(pk=self.b.cost.pk).exists())

    def test_the_cost_download_holds_only_this_project(self):
        from io import BytesIO

        from openpyxl import load_workbook

        response = self.client.get(reverse('costing:cost-report-xlsx'))
        cells = {str(c.value) for row in load_workbook(BytesIO(response.content)).active.iter_rows() for c in row}
        self.assertIn(self.a.cost.voucher_no, cells)
        self.assertNotIn(self.b.cost.voucher_no, cells)

    def test_sales_and_payments(self):
        self.assertIn(self.a.sale.sale_no, self.text('sales:list'))
        self.assertNotIn(self.b.sale.sale_no, self.text('sales:list'))
        payments = self.text('sales:payment-list')
        self.assertIn(reverse('sales:payment-receipt', args=[self.a.payment.pk]), payments)
        self.assertNotIn(reverse('sales:payment-receipt', args=[self.b.payment.pk]), payments)
        for name, obj in (('sales:detail', self.b.sale), ('sales:invoice', self.b.sale), ('sales:update', self.b.sale),
                          ('sales:cancel', self.b.sale), ('sales:payment-receipt', self.b.payment)):
            self.assertEqual(self.client.get(reverse(name, args=[obj.pk])).status_code, 404, name)
        self.assertEqual(self.client.get(reverse('sales:detail', args=[self.a.sale.pk])).status_code, 200)

    def test_customers_and_suppliers_are_shared_by_every_project(self):
        customers = self.text('customers:list')
        self.assertIn('Buyer of Tower A', customers)
        self.assertIn('Buyer of Tower B', customers)
        suppliers = self.text('suppliers:list')
        self.assertIn('Supplier of Tower A', suppliers)
        self.assertIn('Supplier of Tower B', suppliers)
        self.assertEqual(self.client.get(reverse('customers:detail', args=[self.b.customer.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse('suppliers:ledger', args=[self.b.supplier.pk])).status_code, 200)

    def test_a_suppliers_page_inside_a_project_lists_only_that_projects_payments(self):
        other = ProjectCost.objects.create(
            project=self.b.building, cost_category=self.category, date='2026-02-01', amount=77, account=self.bank, supplier=self.a.supplier,
        )
        page = self.text('suppliers:detail', self.a.supplier.pk)
        self.assertIn('Tower A', page)
        self.assertNotIn('Tower B', page)
        self.assertEqual(other.supplier, self.a.supplier)

    def test_a_customer_of_two_projects_shows_only_this_projects_flats(self):
        extra = FlatSale.objects.create(flat=self.b.flats[1], customer=self.a.customer, sale_date='2026-01-03', sale_value=900)
        page = self.text('customers:detail', self.a.customer.pk)
        self.assertIn(self.a.sale.sale_no, page)
        self.assertNotIn(extra.sale_no, page)

    def test_budgets(self):
        from costing.models import ProjectBudget

        ProjectBudget.objects.create(project=self.a.building, cost_category=self.category, budget_amount=100)
        ProjectBudget.objects.create(project=self.b.building, cost_category=self.category, budget_amount=777)
        page = self.text('costing:budget-list')
        self.assertIn('Tower A', page)
        self.assertNotIn('Tower B', page)

    def test_directors_are_shared_and_keep_all_their_projects(self):
        DirectorTransaction.objects.create(
            director=self.director, development=self.b.development, kind='WITHDRAWAL', date='2026-02-01', amount=300, account=self.bank,
        )
        page = self.text('directors:detail', self.director.pk)
        self.assertIn('Alpha', page)
        self.assertIn('Beta', page)
        withdrawal = DirectorTransaction.objects.get(development=self.b.development, kind='WITHDRAWAL')
        self.assertEqual(self.client.get(reverse('directors:transaction-update', args=[withdrawal.pk])).status_code, 200)

    def test_reports_are_about_this_project_whatever_the_link_says(self):
        page = self.text('reports:finance', development=self.b.development.pk)
        self.assertIn('Tower A', page)
        self.assertNotIn('Tower B', page)

    def test_the_dashboard_counts_only_this_project(self):
        response = self.client.get(reverse('home'))
        self.assertEqual(response.context['flat_count'], 2)
        self.assertEqual((response.context['customer_count'], response.context['supplier_count']), (2, 2))
        self.assertEqual(response.context['project_count'], 1)
        self.assertEqual(response.context['total_sales'], D('1500'))
        self.assertEqual(response.context['total_cost'], D('200'))

    def test_reminders_list_only_this_projects_dues(self):
        page = self.text('sms:reminders')
        self.assertIn('Buyer of Tower A', page)
        self.assertNotIn('Buyer of Tower B', page)


class FormsOfferOnlyTheProjectTests(WorkspaceTestCase):
    def setUp(self):
        super().setUp()
        self.enter(self.a.development)

    def test_a_cost_form_offers_only_this_projects_buildings(self):
        form = self.client.get(reverse('costing:cost-create-shared')).context['form']
        self.assertEqual(list(form.fields['project'].queryset), [self.a.building])
        self.assertEqual(form.initial['project'], self.a.building.pk)  # the only choice is preselected

    def test_a_cost_cannot_be_saved_against_another_projects_building(self):
        data = {
            'project': self.b.building.pk, 'cost_category': self.category.pk, 'date': '2026-03-01', 'amount': '50',
            'account': self.bank.pk, 'description': 'x', 'paid_to': 'Cash vendor',
        }
        response = self.client.post(reverse('costing:cost-create-shared'), data)
        self.assertEqual(response.status_code, 200)  # form shown again with an error
        self.assertFalse(ProjectCost.objects.filter(project=self.b.building, amount=50).exists())

    def test_a_cost_can_be_saved_in_the_project(self):
        data = {
            'project': self.a.building.pk, 'cost_category': self.category.pk, 'date': '2026-03-01', 'amount': '50',
            'account': self.bank.pk, 'description': 'x', 'paid_to': 'Cash vendor',
        }
        self.assertEqual(self.client.post(reverse('costing:cost-create-shared'), data).status_code, 302)
        self.assertTrue(ProjectCost.objects.filter(project=self.a.building, amount=50).exists())

    def test_a_payment_form_offers_only_this_projects_sales(self):
        invoice = self.a.sale.booking_invoice
        form = self.client.get(reverse('sales:payment-create'), {'invoice': invoice.pk}).context['form']
        self.assertEqual(list(form.fields['invoice'].queryset), [invoice])
        # another project's invoice cannot be opened for payment from here
        self.assertEqual(self.client.get(reverse('sales:payment-create'), {'invoice': self.b.sale.booking_invoice.pk}).status_code, 302)

    def test_a_sale_form_offers_only_this_projects_flats(self):
        form = self.client.get(reverse('sales:create')).context['form']
        self.assertTrue(set(form.fields['flat'].queryset) <= set(Flat.objects.filter(project=self.a.building)))
        self.assertNotIn(self.b.flats[1], form.fields['flat'].queryset)

    def test_a_new_building_is_added_to_this_project(self):
        form = self.client.get(reverse('projects:create')).context['form']
        self.assertEqual(list(form.fields['development'].queryset), [self.a.development])
        self.assertEqual(form.initial['development'], self.a.development.pk)

    def test_a_director_transaction_is_recorded_in_this_project(self):
        form = self.client.get(reverse('directors:transaction-create')).context['form']
        self.assertEqual(list(form.fields['development'].queryset), [self.a.development])

    def test_switching_project_changes_what_the_form_offers(self):
        self.enter(self.b.development)
        form = self.client.get(reverse('costing:cost-create-shared')).context['form']
        self.assertEqual(list(form.fields['project'].queryset), [self.b.building])


class BookInsideAProjectTests(WorkspaceTestCase):
    def test_only_the_projects_entries_are_collected_and_transfers_are_left_out(self):
        from books.models import Transfer

        other_bank = make_account('Bank 2')
        Transfer.objects.create(from_account=self.bank, to_account=other_bank, date='2026-01-07', amount=10)
        everything = collect_entries()
        inside = collect_entries(development=self.a.development)
        self.assertEqual(len(everything), 3 * 2 + 2)  # payment, cost, investment per project, plus transfer out and in
        self.assertEqual({e.key.split(':')[0] for e in inside}, {'cp', 'pc', 'dt'})
        self.assertEqual(len(inside), 3)
        self.assertTrue(all(self.a.building.project_code in e.description or e.source.startswith(('Payment', 'Director'))
                            for e in inside))

    def test_the_book_page_shows_this_projects_confirmed_entries_only(self):
        for item in (self.a.payment, self.b.payment):
            item.confirmed_at = '2026-01-06T00:00:00Z'
            item.save(update_fields=['confirmed_at'])
        self.enter(self.a.development)
        page = self.text('books:book', date_from='2026-01-01', date_to='2026-12-31')
        self.assertIn(self.a.payment.receipt_no, page)
        self.assertNotIn(self.b.payment.receipt_no, page)

    def test_the_account_list_counts_only_this_projects_waiting_entries(self):
        self.assertEqual(pending_count(), 6)
        self.assertEqual(pending_count(self.a.development), 3)
        row = account_summaries([self.bank], self.a.development)[0]
        self.assertEqual((row['opening'], row['pending_count']), (D('0'), 3))

    def test_the_confirm_page_lists_only_this_projects_entries(self):
        self.enter(self.a.development)
        page = self.text('books:to-confirm', account=self.bank.pk)
        self.assertIn(self.a.payment.receipt_no, page)
        self.assertNotIn(self.b.payment.receipt_no, page)
