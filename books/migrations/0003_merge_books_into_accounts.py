import django.core.validators
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def copy_bank_accounts(apps, schema_editor):
    """Old bank accounts become Accounts of type Bank. Their running balance is dropped: it is now
    worked out from the collected entries (opening balance + money in - money out)."""
    BankAccount = apps.get_model('books', 'BankAccount')
    Account = apps.get_model('books', 'Account')
    for old in BankAccount.objects.order_by('id'):
        Account.objects.create(
            name=old.name, account_type='BANK', bank_name=old.bank_name, account_number=old.account_number,
            branch=old.branch, bank_kind=old.account_type, opening_balance=old.opening_balance,
            is_active=old.is_active, notes=old.notes,
        )


def ensure_petty_cash(apps, schema_editor):
    Account = apps.get_model('books', 'Account')
    if not Account.objects.filter(account_type='CASH').exists():
        Account.objects.create(name='Petty cash', account_type='CASH')


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('books', '0002_drop_manual_books'),
    ]

    operations = [
        migrations.CreateModel(
            name='Account',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(help_text='e.g. Bank 1, Bank 2, Petty cash', max_length=100)),
                ('account_type', models.CharField(choices=[('BANK', 'Bank'), ('CASH', 'Cash')], default='BANK', max_length=10)),
                ('bank_name', models.CharField(blank=True, max_length=100)),
                ('account_number', models.CharField(blank=True, max_length=50)),
                ('branch', models.CharField(blank=True, max_length=100)),
                ('bank_kind', models.CharField(
                    blank=True, max_length=20, verbose_name='Account kind',
                    choices=[('CURRENT', 'Current Account'), ('SAVINGS', 'Savings Account'), ('FIXED', 'Fixed Deposit')])),
                ('opening_balance', models.DecimalField(decimal_places=2, default=0, max_digits=14)),
                ('is_active', models.BooleanField(default=True)),
                ('notes', models.TextField(blank=True)),
            ],
            options={
                'ordering': ['account_type', 'name'],
                'permissions': [('confirm_entries', 'Can confirm book entries')],
            },
        ),
        migrations.RunPython(copy_bank_accounts, migrations.RunPython.noop),
        migrations.DeleteModel(name='BankAccount'),
        migrations.CreateModel(
            name='Transfer',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('confirmed_at', models.DateTimeField(blank=True, editable=False, null=True)),
                ('date', models.DateField()),
                ('amount', models.DecimalField(decimal_places=2, max_digits=14, validators=[django.core.validators.MinValueValidator(0.01)])),
                ('notes', models.CharField(blank=True, max_length=300)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('confirmed_by', models.ForeignKey(blank=True, editable=False, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('from_account', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='transfers_out', to='books.account')),
                ('to_account', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='transfers_in', to='books.account')),
            ],
            options={'ordering': ['-date', '-id']},
        ),
        migrations.RunPython(ensure_petty_cash, migrations.RunPython.noop),
    ]
