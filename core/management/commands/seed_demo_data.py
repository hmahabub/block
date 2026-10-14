import datetime
from decimal import Decimal

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Sum

from books.models import Account, Transfer
from costing.models import CostCategory, ProjectCost
from customers.models import Customer
from projects.models import Flat, Project
from sales.models import CustomerPayment, FlatSale, HonorariumPayment, Reference

FLOORS = 12
UNITS_PER_FLOOR = 4
FLAT_AREA = Decimal('1700')
PARKING_AREA = Decimal('120')
# Placeholder prices for the demo; the real ones are set once on each project.
BASE_PRICE = Decimal('13500000')    # what the company needs from each flat share
QUOTED_PRICE = Decimal('15300000')  # price quoted to buyers (9,000 per sqft)
PARKING_PRICE = Decimal('500000')   # extra when the buyer takes the parking lot
REG_VALUE = Decimal('150000')       # registration cost, paid by the customer
PROJECT_BUDGET = Decimal('5000000')
INITIAL_PAYMENT = {'Tower 1': Decimal('2300000'), 'Tower 2': Decimal('2100000')}
PAID_FROM = {'Tower 1': 'Bank 1', 'Tower 2': 'Bank 2'}  # the account each tower's money moves through

ACCOUNTS = [
    dict(name='Bank 1', account_type='BANK', bank_name='Demo Bank Ltd', account_number='1001-200-300', opening_balance=20_000_000),
    dict(name='Bank 2', account_type='BANK', bank_name='Sample Bank PLC', account_number='2002-400-500', opening_balance=8_000_000),
]
REFERENCES = [
    dict(name='Mr. Alam (reference)', phone='+8801811100001'),
    dict(name='Ms. Sultana (reference)', phone='+8801811100002'),
]

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
    dict(title='MR', whatsapp_no='+8801711100001', tin='123456789012',
         emergency_contact_name='Salma Akter', emergency_contact_phone='+8801711100011',
         name='Rahim Uddin', phone='+8801711100001', email='rahim.uddin@example.com',
         identification_no='1985123456701', date_of_birth=datetime.date(1985, 4, 12), occupation='Businessman',
         father_name='Abdul Karim Uddin', mother_name='Amina Begum', spouse_name='Salma Akter',
         nominee_name='Salma Akter', nominee_relation='Wife',
         present_address='House 12, Road 5, Gulshan-1, Dhaka', permanent_address='Village Rampur, Comilla'),
    dict(title='MS', whatsapp_no='+8801711100002', tin='223456789012',
         emergency_contact_name='Dr. Shafiq Ahmed', emergency_contact_phone='+8801711100012',
         name='Nasrin Akter', phone='+8801711100002', email='nasrin.akter@example.com',
         identification_no='1990123456702', date_of_birth=datetime.date(1990, 9, 3), occupation='Doctor',
         father_name='Md. Jahangir Alam', mother_name='Rokeya Khatun', spouse_name='Dr. Shafiq Ahmed',
         nominee_name='Dr. Shafiq Ahmed', nominee_relation='Husband',
         present_address='Flat 4B, Dhanmondi 27, Dhaka', permanent_address='Zilla Road, Rajshahi'),
    dict(title='MR', whatsapp_no='+8801711100003', tin='323456789012',
         emergency_contact_name='Shirin Sultana', emergency_contact_phone='+8801711100013',
         name='Kamal Hossain', phone='+8801711100003', email='kamal.hossain@example.com',
         identification_no='1978123456703', date_of_birth=datetime.date(1978, 1, 20), occupation='Engineer',
         father_name='Late Abul Hossain', mother_name='Hasina Begum', spouse_name='Shirin Sultana',
         nominee_name='Shirin Sultana', nominee_relation='Wife',
         present_address='House 7, Sector 4, Uttara, Dhaka', permanent_address='Boro Bazar, Sylhet'),
    dict(title='MS', whatsapp_no='+8801711100004', tin='423456789012',
         emergency_contact_name='Tanvir Rahman', emergency_contact_phone='+8801711100014',
         name='Farhana Yasmin', phone='+8801711100004', email='farhana.yasmin@example.com',
         identification_no='1988123456704', date_of_birth=datetime.date(1988, 6, 30), occupation='Banker',
         father_name='Md. Nurul Islam', mother_name='Jahanara Begum', spouse_name='Tanvir Rahman',
         nominee_name='Tanvir Rahman', nominee_relation='Husband',
         present_address='Apt 9C, Bashundhara R/A, Dhaka', permanent_address='College Road, Barishal'),
]

# (customer, tower, flat, booking date, parking taken, sale value, reference index):
# 3 flats in each tower, all four customers used; flat A1 = unit A on floor 1.
BOOKINGS = [
    ('Rahim Uddin', 'Tower 1', 'A1', '2026-09-02', False, QUOTED_PRICE, 0),
    ('Nasrin Akter', 'Tower 1', 'B4', '2026-09-05', True, QUOTED_PRICE + PARKING_PRICE, 1),
    ('Kamal Hossain', 'Tower 1', 'C8', '2026-09-09', False, QUOTED_PRICE + Decimal('200000'), 0),
    ('Farhana Yasmin', 'Tower 2', 'B2', '2026-09-12', False, QUOTED_PRICE, 1),
    ('Rahim Uddin', 'Tower 2', 'C5', '2026-09-16', True, QUOTED_PRICE + PARKING_PRICE, 0),
    ('Nasrin Akter', 'Tower 2', 'D12', '2026-09-20', False, QUOTED_PRICE, None),
]


class Command(BaseCommand):
    help = 'Loads demo data: Tower 1 and Tower 2 (12 floors x 4 flats), accounts, 4 customers, 6 bookings, costs.'

    @transaction.atomic
    def handle(self, *args, **options):
        if Project.objects.exists() or Customer.objects.exists():
            raise CommandError('The database already has projects or customers; run this on a fresh database.')

        call_command('seed_cost_categories', verbosity=0)
        accounts = self.create_accounts()
        projects = {name: self.create_tower(name) for name in ('Tower 1', 'Tower 2')}
        customers = {data['name']: Customer.objects.create(**data) for data in CUSTOMERS}
        references = [Reference.objects.create(**data) for data in REFERENCES]
        self.create_bookings(projects, customers, references, accounts)
        self.create_costs(projects, accounts)
        Transfer.objects.create(
            date='2026-09-25', from_account=accounts['Bank 1'], to_account=accounts['Petty cash'],
            amount=100_000, notes='Cash for site expenses',
        )
        self.confirm_first_tower(accounts)
        self.report()

    def confirm_first_tower(self, accounts):
        """Tower 1's money (through Bank 1) is already confirmed in the book; Tower 2's still waits on the
        Confirm entries page, so the demo shows both states."""
        from books.ledger import collect_entries, confirm_entries

        keys = [e.key for e in collect_entries([accounts['Bank 1']], confirmed=False)]
        done, problems = confirm_entries(keys, None)
        assert not problems, problems

    def create_accounts(self):
        accounts = {data['name']: Account.objects.create(**data) for data in ACCOUNTS}
        accounts['Petty cash'], _ = Account.objects.get_or_create(
            name='Petty cash', defaults={'account_type': Account.AccountType.CASH},
        )
        return accounts

    def create_tower(self, name):
        project = Project.objects.create(
            project_name=name, floor_no=FLOORS, budget_amount=PROJECT_BUDGET, status=Project.Status.ONGOING,
            description=f'{name}: {FLOORS} floors, {UNITS_PER_FLOOR} flats per floor.',
            flat_type=Project.FlatType.FOUR_BED, flat_area=FLAT_AREA, parking_area=PARKING_AREA,
            bedrooms=4, bathrooms=4, features='Drawing, Dining, Balcony & others included',
            base_price=BASE_PRICE, quoted_price=QUOTED_PRICE, parking_price=PARKING_PRICE,
        )
        for floor in range(1, FLOORS + 1):
            for index in range(UNITS_PER_FLOOR):
                Flat.objects.create(project=project, unit=chr(65 + index), floor_no=floor)
        return project

    def create_bookings(self, projects, customers, references, accounts):
        for customer_name, tower, flat_no, date, parking, sale_value, ref_index in BOOKINGS:
            flat = Flat.objects.get(project=projects[tower], flat_no=flat_no)
            sale = FlatSale.objects.create(
                flat=flat, customer=customers[customer_name], sale_date=date, with_parking=parking,
                sale_value=sale_value, reg_value=REG_VALUE,
                ref=references[ref_index] if ref_index is not None else None,
            )
            CustomerPayment.objects.create(
                sale=sale, payment_date=date, amount=INITIAL_PAYMENT[tower], account=accounts[PAID_FROM[tower]],
                reference_no=f'INITIAL-{sale.sale_no[-5:]}', notes='Initial booking payment',
            )
        # Part of the first booking's honorarium has already been paid to its reference.
        first = FlatSale.objects.order_by('id').first()
        if first.honorarium > 0:
            HonorariumPayment.objects.create(
                sale=first, date='2026-09-20', amount=first.honorarium / 2, account=accounts['Bank 1'],
                notes='Part payment',
            )

    def create_costs(self, projects, accounts):
        for tower, project in projects.items():
            for (parent, name, amount, description), date in zip(COSTS, COST_DATES[tower]):
                category = CostCategory.objects.get(name=name, parent_category__name=parent)
                ProjectCost.objects.create(
                    project=project, cost_category=category, date=date, amount=amount, description=description,
                    account=accounts[PAID_FROM[tower]],
                )

    def report(self):
        total_cost = ProjectCost.objects.aggregate(t=Sum('amount'))['t']
        self.stdout.write(self.style.SUCCESS(
            f'Created {Project.objects.count()} projects, {Flat.objects.count()} flats, '
            f'{Customer.objects.count()} customers, {FlatSale.objects.count()} bookings, '
            f'{CustomerPayment.objects.count()} payments; total cost {total_cost:,.2f}.'
        ))
