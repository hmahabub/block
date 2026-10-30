from django.core.management import call_command
from django.test import TestCase


class SeedStructureTests(TestCase):
    """The demo data shows the new structure: a project with buildings, directors, own parking price."""

    @classmethod
    def setUpTestData(cls):
        call_command('seed_demo_data')

    def test_one_project_holds_both_towers(self):
        from projects.models import Development, Project
        development = Development.objects.get()
        self.assertEqual(development.building_count, 2)
        self.assertEqual({b.project_name for b in development.buildings.all()}, {'Tower 1', 'Tower 2'})
        self.assertEqual(Project.objects.filter(development__isnull=True).count(), 0)

    def test_customers_have_ids(self):
        from customers.models import Customer
        self.assertEqual(sorted(Customer.objects.values_list('customer_code', flat=True)), ['C0001', 'C0002', 'C0003', 'C0004'])

    def test_directors_invested_and_took_some_back(self):
        from directors.models import Director, totals_for
        self.assertEqual(Director.objects.count(), 3)
        figures = totals_for()
        self.assertEqual((figures['invested'], figures['withdrawn'], figures['outstanding']), (35_000_000, 3_000_000, 32_000_000))

    def test_director_money_is_in_the_book_waiting_or_confirmed(self):
        from books.ledger import collect_entries
        sources = {e.source for e in collect_entries()}
        self.assertIn('Director investment', sources)
        self.assertIn('Director capital withdrawal', sources)

    def test_one_flat_has_its_own_parking_price(self):
        from projects.models import Flat
        flat = Flat.objects.get(project__project_name='Tower 1', flat_no='B4')
        self.assertEqual(flat.parking_price, 650_000)
        self.assertEqual(flat.effective_parking_price, 650_000)
        other = Flat.objects.get(project__project_name='Tower 1', flat_no='A1')
        self.assertEqual(other.effective_parking_price, 500_000)
        from sales.models import FlatSale
        self.assertEqual(FlatSale.objects.get(flat=flat).parking_price, 650_000)

    def test_everything_made_by_the_seed_is_in_the_audit_trail(self):
        from activity_log.models import ActivityLog
        names = set(ActivityLog.objects.values_list('model_name', flat=True))
        for expected in ('Development', 'Project', 'Flat', 'Customer', 'FlatSale', 'CustomerPayment', 'ProjectCost', 'Director', 'DirectorTransaction'):
            self.assertIn(expected, names)
