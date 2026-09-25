import datetime
from decimal import Decimal

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Sum

from costing.models import CostCategory, ProjectCost
from customers.models import Customer
from projects.models import Flat, Project
from sales.models import CustomerPayment, FlatSale

FLOORS = 12
UNITS_PER_FLOOR = 4
FLAT_AREA = Decimal('1700')
PARKING_AREA = Decimal('120')
PRICE_PER_SQFT = Decimal('9000')  # placeholder price; edit real prices on each flat
PROJECT_BUDGET = Decimal('5000000')
INITIAL_PAYMENT = {'Tower 1': Decimal('2300000'), 'Tower 2': Decimal('2100000')}

# (parent category, category, amount, description): 7,500,000 per tower, 15,000,000 in total
COSTS = [
    ('Land', 'Land Purchase', 4_000_000, 'Land purchase'),
    ('Development', 'Architect', 800_000, 'Architectural design fees'),
    ('Development', 'Approval', 500_000, 'Building plan approval fees'),
    ('Construction', 'Civil', 1_700_000, 'Foundation and civil work - stage 1'),
    ('Construction', 'Cement', 500_000, 'Cement purchase'),
]
COST_DATES = {
    'Tower 1': ['2026-05-10', '2026-06-05', '2026-06-20', '2026-08-15', '2026-09-05'],
    'Tower 2': ['2026-05-24', '2026-06-12', '2026-07-01', '2026-08-28', '2026-09-12'],
}

CUSTOMERS = [
    dict(name='Rahim Uddin', phone='+8801711100001', email='rahim.uddin@example.com',
         identification_no='1985123456701', date_of_birth=datetime.date(1985, 4, 12), occupation='Businessman',
         father_name='Abdul Karim Uddin', mother_name='Amina Begum', spouse_name='Salma Akter',
         nominee_name='Salma Akter', nominee_relation='Wife',
         present_address='House 12, Road 5, Gulshan-1, Dhaka', permanent_address='Village Rampur, Comilla'),
    dict(name='Nasrin Akter', phone='+8801711100002', email='nasrin.akter@example.com',
         identification_no='1990123456702', date_of_birth=datetime.date(1990, 9, 3), occupation='Doctor',
         father_name='Md. Jahangir Alam', mother_name='Rokeya Khatun', spouse_name='Dr. Shafiq Ahmed',
         nominee_name='Dr. Shafiq Ahmed', nominee_relation='Husband',
         present_address='Flat 4B, Dhanmondi 27, Dhaka', permanent_address='Zilla Road, Rajshahi'),
    dict(name='Kamal Hossain', phone='+8801711100003', email='kamal.hossain@example.com',
         identification_no='1978123456703', date_of_birth=datetime.date(1978, 1, 20), occupation='Engineer',
         father_name='Late Abul Hossain', mother_name='Hasina Begum', spouse_name='Shirin Sultana',
         nominee_name='Shirin Sultana', nominee_relation='Wife',
         present_address='House 7, Sector 4, Uttara, Dhaka', permanent_address='Boro Bazar, Sylhet'),
    dict(name='Farhana Yasmin', phone='+8801711100004', email='farhana.yasmin@example.com',
         identification_no='1988123456704', date_of_birth=datetime.date(1988, 6, 30), occupation='Banker',
         father_name='Md. Nurul Islam', mother_name='Jahanara Begum', spouse_name='Tanvir Rahman',
         nominee_name='Tanvir Rahman', nominee_relation='Husband',
         present_address='Apt 9C, Bashundhara R/A, Dhaka', permanent_address='College Road, Barishal'),
]

# (customer, tower, flat number, booking date): 3 flats in each tower, all four customers used
BOOKINGS = [
    ('Rahim Uddin', 'Tower 1', '101', '2026-09-02'),
    ('Nasrin Akter', 'Tower 1', '402', '2026-09-05'),
    ('Kamal Hossain', 'Tower 1', '803', '2026-09-09'),
    ('Farhana Yasmin', 'Tower 2', '202', '2026-09-12'),
    ('Rahim Uddin', 'Tower 2', '503', '2026-09-16'),
    ('Nasrin Akter', 'Tower 2', '1204', '2026-09-20'),
]


class Command(BaseCommand):
    help = 'Loads demo data: Tower 1 and Tower 2 (12 floors x 4 flats), 4 customers, 6 bookings, costs.'

    @transaction.atomic
    def handle(self, *args, **options):
        if Project.objects.exists() or Customer.objects.exists():
            raise CommandError('The database already has projects or customers; run this on a fresh database.')

        call_command('seed_cost_categories', verbosity=0)
        projects = {name: self.create_tower(name) for name in ('Tower 1', 'Tower 2')}
        customers = {data['name']: Customer.objects.create(**data) for data in CUSTOMERS}
        self.create_bookings(projects, customers)
        self.create_costs(projects)
        self.report()

    def create_tower(self, name):
        project = Project.objects.create(
            project_name=name, floor_no=FLOORS, total_saleable_area=FLAT_AREA * FLOORS * UNITS_PER_FLOOR,
            budget_amount=PROJECT_BUDGET, status=Project.Status.ONGOING,
            description=f'{name}: {FLOORS} floors, {UNITS_PER_FLOOR} flats per floor.',
        )
        Flat.objects.bulk_create([
            Flat(
                project=project, flat_no=str(floor * 100 + unit), floor_no=floor, flat_type=Flat.FlatType.FOUR_BED,
                saleable_area=FLAT_AREA, base_price=FLAT_AREA * PRICE_PER_SQFT, parking_area=PARKING_AREA,
                bedrooms=4, bathrooms=4, features='Drawing, Dining, Balcony & others included',
            )
            for floor in range(1, FLOORS + 1) for unit in range(1, UNITS_PER_FLOOR + 1)
        ])
        return project

    def create_bookings(self, projects, customers):
        for customer_name, tower, flat_no, date in BOOKINGS:
            flat = Flat.objects.get(project=projects[tower], flat_no=flat_no)
            sale = FlatSale.objects.create(
                flat=flat, customer=customers[customer_name], sale_date=date, base_price=flat.base_price,
            )
            CustomerPayment.objects.create(
                sale=sale, payment_date=date, amount=INITIAL_PAYMENT[tower],
                payment_method=CustomerPayment.Method.BANK, reference_no=f'INITIAL-{sale.sale_no[-5:]}',
                notes='Initial booking payment',
            )

    def create_costs(self, projects):
        for tower, project in projects.items():
            for (parent, name, amount, description), date in zip(COSTS, COST_DATES[tower]):
                category = CostCategory.objects.get(name=name, parent_category__name=parent)
                ProjectCost.objects.create(
                    project=project, cost_category=category, date=date, amount=amount, description=description,
                )

    def report(self):
        total_cost = ProjectCost.objects.aggregate(t=Sum('amount'))['t']
        self.stdout.write(self.style.SUCCESS(
            f'Created {Project.objects.count()} projects, {Flat.objects.count()} flats, '
            f'{Customer.objects.count()} customers, {FlatSale.objects.count()} bookings, '
            f'{CustomerPayment.objects.count()} payments; total cost {total_cost:,.2f}.'
        ))
