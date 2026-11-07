from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import ProtectedError

from costing.models import CostCategory

PRE = CostCategory.CategoryPhase.PRE
POST = CostCategory.CategoryPhase.POST

# The operating costs are the same before and after construction starts.
OPERATING_COSTS = [
    'Salary & Bonus',
    'Office Rent',
    'Utility Bills (Electricity, Water, Gas, Internet)',
    'Administrative Costs (Stationery, Legal, Postage)',
    'Advertisement & Marketing Cost',
    'Maintenance Cost',
    'Conveyance & Entertainment',
    'Donation & Subsidy Costs',
    'Honorarium for Directors',
    'Extra Commission',
    'Miscellaneous Costs',
]

# (head, phase, [cost heads under it])
CATEGORY_TREE = [
    # --- Pre-construction: the company's cost, set against the profit on share sales -------------
    ('Land Related Costs', PRE, [
        'Total Land Area (Katha)',
        'Land Value / Actual Land Payment',
        'Media Fee (Land Purchase)',
        'Legal Cost & Registration Fee',
        'Site Development Cost',
        'Estimated Sales Duration',
        'Other Costs',
    ]),
    ('Operating Costs (Pre-Construction)', PRE, OPERATING_COSTS),

    # --- Post-construction: borne equally by the owners of every flat --------------------------
    ('Structural & Materials Cost', POST, [
        'Structural Cost', 'Finishing Cost', 'Lift', 'Generator', 'Sub-Station', 'Paint', 'Brick', 'Cement', 'Rod', 'Tiles',
        'Civil Cost', 'Electrical Cost', 'Other Related Costs',
    ]),
    ('Building / Project Specifications & Unit Budgeting', POST, [
        'Total Number of Floors & Units',
        'Commercial Area Details',
        'Per SFT Budget (Residential & Commercial)',
        'Individual Unit Size',
    ]),
    ('Approvals & Site Setup', POST, [
        'CDA Cost / LUC / Final Approval Costs',
        'Architect, Soil Test & Legal Fees',
        'Site Mobilization Budget (Deep Tubewell, Labour Shed, Temporary Office, TC Meter, Boundary Wall, Security)',
    ]),
    ('Operating Costs (Post-Construction)', POST, OPERATING_COSTS),
]


class Command(BaseCommand):
    help = (
        'Loads the standard cost heads (Pre-Construction: land and operating costs; Post-Construction: structural, '
        'specifications, approvals and operating costs). Use --replace to delete the existing cost heads first.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--replace', action='store_true',
            help='Delete every existing cost category first. Refused if any cost or budget still uses one.',
        )

    def handle(self, *args, **options):
        if options['replace']:
            self.delete_all()
        created_count = 0
        for top_name, phase, children in CATEGORY_TREE:
            top, created = CostCategory.objects.get_or_create(name=top_name, parent_category=None, defaults={'phase': phase})
            created_count += int(created)
            if top.phase != phase:
                top.phase = phase
                top.save()  # sub-categories follow their parent
            for child_name in children:
                _, created = CostCategory.objects.get_or_create(name=child_name, parent_category=top)
                created_count += int(created)
        self.stdout.write(self.style.SUCCESS(f'Cost categories seeded ({created_count} created).'))

    def delete_all(self):
        count = CostCategory.objects.count()
        try:
            with transaction.atomic():   # all or nothing
                for category in CostCategory.objects.filter(parent_category__isnull=False):
                    category.delete()
                for category in CostCategory.objects.all():
                    category.delete()
        except ProtectedError as error:
            raise CommandError(
                'Some cost categories are used by recorded costs or budgets and cannot be deleted. '
                f'Nothing was changed. ({error.args[0]})'
            ) from error
        self.stdout.write(f'Deleted {count} existing cost categories.')
