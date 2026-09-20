from django.core.management.base import BaseCommand

from costing.models import CostCategory

CATEGORY_TREE = {
    'Land': ['Land Purchase', 'Registration', 'Legal', 'Other Land Cost'],
    'Development': ['Architect', 'Design', 'Approval', 'Soil Test', 'Other Development'],
    'Construction': [
        'Civil', 'Rod', 'Cement', 'Brick', 'Electrical', 'Plumbing',
        'Tiles', 'Paint', 'Lift', 'Other Construction',
    ],
    'Finance': ['Bank Interest', 'Other Finance Cost'],
    'Marketing': ['Advertisement', 'Commission', 'Promotion'],
    'Administration': ['Office', 'Salary', 'Legal', 'Other'],
    'Post-Completion': ['Repair', 'Maintenance', 'Handover', 'Warranty'],
}


class Command(BaseCommand):
    help = 'Seeds the standard real-estate cost category tree (Land, Development, Construction, ...).'

    def handle(self, *args, **options):
        created_count = 0
        for top_name, children in CATEGORY_TREE.items():
            top, created = CostCategory.objects.get_or_create(name=top_name, parent_category=None)
            created_count += int(created)
            for child_name in children:
                _, created = CostCategory.objects.get_or_create(name=child_name, parent_category=top)
                created_count += int(created)
        self.stdout.write(self.style.SUCCESS(f'Cost categories seeded ({created_count} created).'))
