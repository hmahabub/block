"""The standard cost heads: Pre-Construction (land, operating) and Post-Construction (structural, specs, approvals, operating)."""
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from core.testing import make_account, make_project

from .management.commands.seed_cost_categories import CATEGORY_TREE, OPERATING_COSTS
from .models import CostCategory, ProjectCost

PRE_HEADS = ['Land Related Costs', 'Operating Costs (Pre-Construction)']
POST_HEADS = [
    'Structural & Materials Cost', 'Building / Project Specifications & Unit Budgeting', 'Approvals & Site Setup',
    'Operating Costs (Post-Construction)',
]


def children(head):
    return sorted(CostCategory.objects.get(name=head, parent_category=None).subcategories.values_list('name', flat=True))


class SeedCategoriesTests(TestCase):
    def seed(self, *args):
        call_command('seed_cost_categories', *args, verbosity=0)

    def test_the_heads_and_their_phases(self):
        self.seed()
        tops = {c.name: c.phase for c in CostCategory.objects.filter(parent_category__isnull=True)}
        self.assertEqual(tops, {**{h: 'PRE' for h in PRE_HEADS}, **{h: 'POST' for h in POST_HEADS}})

    def test_land_related_costs(self):
        self.seed()
        self.assertEqual(children('Land Related Costs'), sorted([
            'Total Land Area (Katha)', 'Land Value / Actual Land Payment', 'Media Fee (Land Purchase)',
            'Legal Cost & Registration Fee', 'Site Development Cost', 'Estimated Sales Duration', 'Other Costs',
        ]))

    def test_the_operating_costs_are_the_same_before_and_after_construction(self):
        self.seed()
        self.assertEqual(len(OPERATING_COSTS), 11)
        self.assertEqual(children('Operating Costs (Pre-Construction)'), sorted(OPERATING_COSTS))
        self.assertEqual(children('Operating Costs (Post-Construction)'), sorted(OPERATING_COSTS))
        for name in ('Salary & Bonus', 'Honorarium for Directors', 'Extra Commission', 'Miscellaneous Costs'):
            self.assertIn(name, OPERATING_COSTS)

    def test_post_construction_heads(self):
        self.seed()
        structural = children('Structural & Materials Cost')
        for name in ('Structural Cost', 'Finishing Cost', 'Lift', 'Generator', 'Sub-Station', 'Paint', 'Brick', 'Cement', 'Rod', 'Tiles'):
            self.assertIn(name, structural)
        self.assertEqual(children('Building / Project Specifications & Unit Budgeting'), sorted([
            'Total Number of Floors & Units', 'Commercial Area Details', 'Per SFT Budget (Residential & Commercial)',
            'Individual Unit Size',
        ]))
        approvals = children('Approvals & Site Setup')
        self.assertEqual(len(approvals), 3)
        self.assertIn('CDA Cost / LUC / Final Approval Costs', approvals)
        self.assertIn('Architect, Soil Test & Legal Fees', approvals)
        self.assertTrue(any(name.startswith('Site Mobilization Budget (Deep Tubewell') for name in approvals))

    def test_sub_heads_follow_their_parents_phase(self):
        self.seed()
        self.assertEqual(CostCategory.objects.get(name='Salary & Bonus', parent_category__name='Operating Costs (Pre-Construction)').phase, 'PRE')
        self.assertEqual(CostCategory.objects.get(name='Salary & Bonus', parent_category__name='Operating Costs (Post-Construction)').phase, 'POST')

    def test_every_head_has_a_unique_code_and_fits(self):
        self.seed()
        total = sum(1 + len(kids) for _, _, kids in CATEGORY_TREE)
        self.assertEqual(CostCategory.objects.count(), total)
        self.assertEqual(CostCategory.objects.values('code').distinct().count(), total)

    def test_seeding_twice_changes_nothing(self):
        self.seed()
        count = CostCategory.objects.count()
        self.seed()
        self.assertEqual(CostCategory.objects.count(), count)

    def test_replace_deletes_the_old_heads_and_loads_the_new(self):
        old = CostCategory.objects.create(name='Land', phase='PRE')
        CostCategory.objects.create(name='Registration', parent_category=old)
        self.seed('--replace')
        self.assertFalse(CostCategory.objects.filter(name__in=['Land', 'Registration']).exists())
        self.assertEqual(CostCategory.objects.filter(parent_category__isnull=True).count(), 6)

    def test_replace_is_refused_while_a_recorded_cost_uses_a_head(self):
        old = CostCategory.objects.create(name='Civil', phase='POST')
        project, _ = make_project()
        ProjectCost.objects.create(project=project, cost_category=old, date='2026-01-01', amount=10, account=make_account())
        with self.assertRaises(CommandError):
            self.seed('--replace')
        self.assertTrue(CostCategory.objects.filter(pk=old.pk).exists())           # nothing was deleted
        self.assertFalse(CostCategory.objects.filter(name='Land Related Costs').exists())

    def test_the_demo_data_uses_the_new_heads(self):
        call_command('seed_demo_data', verbosity=0)
        heads = set(ProjectCost.objects.values_list('cost_category__parent_category__name', flat=True))
        self.assertEqual(heads, {'Land Related Costs', 'Approvals & Site Setup', 'Structural & Materials Cost'})
