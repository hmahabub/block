import django.core.validators
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

AMOUNT = dict(decimal_places=2, max_digits=14)


def fill_new_amounts(apps, schema_editor):
    """The old net sale value (base + charges - discount) becomes the sale value, and any payment
    beyond it becomes the customer balance."""
    FlatSale = apps.get_model('sales', 'FlatSale')
    for sale in FlatSale.objects.all():
        FlatSale.objects.filter(pk=sale.pk).update(
            sale_value=sale.net_value,
            customer_balance=max(sale.received_amount - sale.net_value, 0),
        )


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('books', '0003_merge_books_into_accounts'),
        ('projects', '0004_project_level_flat_specs'),
        ('sales', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='Reference',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=150)),
                ('phone', models.CharField(blank=True, max_length=17, validators=[django.core.validators.RegexValidator(
                    regex='^\\+?\\d{9,15}$', message='Phone number must be like +8801711000000 or 01711000000.')])),
                ('notes', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={'verbose_name': 'Reference', 'ordering': ['name']},
        ),

        migrations.RenameField(model_name='flatsale', old_name='net_sale_value', new_name='net_value'),
        migrations.AddField(model_name='flatsale', name='sale_value', field=models.DecimalField(
            default=0, validators=[django.core.validators.MinValueValidator(0)], **AMOUNT)),
        migrations.AddField(model_name='flatsale', name='reg_value', field=models.DecimalField(
            default=0, help_text='Registration cost when the share is registered to the owner; paid by the customer.',
            validators=[django.core.validators.MinValueValidator(0)], verbose_name='Reg value', **AMOUNT)),
        migrations.AddField(model_name='flatsale', name='with_parking', field=models.BooleanField(
            default=False, verbose_name='Includes parking lot')),
        migrations.AddField(model_name='flatsale', name='parking_price', field=models.DecimalField(
            default=0, editable=False, **AMOUNT)),
        migrations.AddField(model_name='flatsale', name='customer_balance', field=models.DecimalField(
            default=0, editable=False, **AMOUNT)),
        migrations.AddField(model_name='flatsale', name='ref', field=models.ForeignKey(
            blank=True, help_text='The reference who receives the honorarium.', null=True,
            on_delete=django.db.models.deletion.SET_NULL, related_name='sales', to='sales.reference', verbose_name='Ref')),
        migrations.AddField(model_name='flatsale', name='cancelled_on', field=models.DateField(blank=True, editable=False, null=True)),
        migrations.AddField(model_name='flatsale', name='refund_percent', field=models.DecimalField(
            blank=True, decimal_places=2, editable=False, max_digits=5, null=True,
            validators=[django.core.validators.MinValueValidator(0), django.core.validators.MaxValueValidator(100)])),
        migrations.AddField(model_name='flatsale', name='refund_amount', field=models.DecimalField(
            default=0, editable=False, **AMOUNT)),
        migrations.RunPython(fill_new_amounts, migrations.RunPython.noop),
        migrations.RemoveField(model_name='flatsale', name='other_charges'),
        migrations.RemoveField(model_name='flatsale', name='discount'),
        migrations.AlterField(model_name='flatsale', name='flat', field=models.ForeignKey(
            on_delete=django.db.models.deletion.PROTECT, related_name='sales', to='projects.flat')),

        migrations.AddField(model_name='customerpayment', name='account', field=models.ForeignKey(
            blank=True, help_text='The bank or cash account the money went into.', null=True,
            on_delete=django.db.models.deletion.PROTECT, related_name='customer_payments', to='books.account',
            verbose_name='Received into')),
        migrations.AddField(model_name='customerpayment', name='confirmed_at', field=models.DateTimeField(blank=True, editable=False, null=True)),
        migrations.AddField(model_name='customerpayment', name='confirmed_by', field=models.ForeignKey(
            blank=True, editable=False, null=True, on_delete=django.db.models.deletion.SET_NULL,
            related_name='+', to=settings.AUTH_USER_MODEL)),

        migrations.CreateModel(
            name='HonorariumPayment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('confirmed_at', models.DateTimeField(blank=True, editable=False, null=True)),
                ('date', models.DateField()),
                ('amount', models.DecimalField(validators=[django.core.validators.MinValueValidator(0.01)], **AMOUNT)),
                ('notes', models.CharField(blank=True, max_length=300)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('account', models.ForeignKey(help_text='The bank or cash account the money was paid from.', on_delete=django.db.models.deletion.PROTECT, related_name='honorarium_payments', to='books.account', verbose_name='Paid from')),
                ('confirmed_by', models.ForeignKey(blank=True, editable=False, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('sale', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='honorarium_payments', to='sales.flatsale')),
            ],
            options={'verbose_name': 'Honorarium Payment', 'ordering': ['-date', '-id']},
        ),
        migrations.CreateModel(
            name='RefundPayment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('confirmed_at', models.DateTimeField(blank=True, editable=False, null=True)),
                ('date', models.DateField()),
                ('amount', models.DecimalField(validators=[django.core.validators.MinValueValidator(0.01)], **AMOUNT)),
                ('notes', models.CharField(blank=True, max_length=300)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('account', models.ForeignKey(help_text='The bank or cash account the money was paid from.', on_delete=django.db.models.deletion.PROTECT, related_name='refund_payments', to='books.account', verbose_name='Paid from')),
                ('confirmed_by', models.ForeignKey(blank=True, editable=False, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('sale', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='refund_payments', to='sales.flatsale')),
            ],
            options={'verbose_name': 'Refund Payment', 'ordering': ['-date', '-id']},
        ),
    ]
