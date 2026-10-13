import re

import django.core.validators
import django.db.models.deletion
from django.db import migrations, models


def add_country_prefix(apps, schema_editor):
    Supplier = apps.get_model('suppliers', 'Supplier')
    for supplier in Supplier.objects.exclude(phone=''):
        number = re.sub(r'[\s\-().]', '', supplier.phone)
        if number.startswith('+'):
            continue
        if number.startswith('0088'):
            new = '+' + number[2:]
        elif number.startswith('88') and len(number) >= 13:
            new = '+' + number
        else:
            new = '+88' + number
        if len(new) <= 17:
            Supplier.objects.filter(pk=supplier.pk).update(phone=new)


class Migration(migrations.Migration):

    dependencies = [
        ('costing', '0004_phases_accounts_equal_sharing'),
        ('suppliers', '0001_initial'),
    ]

    operations = [
        migrations.RenameField(model_name='supplier', old_name='contact_person', new_name='owner_name'),
        migrations.AlterField(model_name='supplier', name='name', field=models.CharField(max_length=150, verbose_name='Company name')),
        migrations.AddField(model_name='supplier', name='email', field=models.EmailField(blank=True, max_length=254)),
        migrations.AddField(model_name='supplier', name='bank_account', field=models.CharField(
            blank=True, help_text='Bank, account name and number.', max_length=150)),
        migrations.AddField(model_name='supplier', name='cost_category', field=models.ForeignKey(
            blank=True, help_text='The kind of work this supplier does (same list as the cost categories).', null=True,
            on_delete=django.db.models.deletion.SET_NULL, related_name='suppliers', to='costing.costcategory',
            verbose_name='Type')),
        migrations.AlterField(model_name='supplier', name='phone', field=models.CharField(
            blank=True, help_text='+88 is added automatically to local numbers.', max_length=17,
            validators=[django.core.validators.RegexValidator(
                regex='^\\+?1?\\d{9,15}$', message="Phone number must be in format: '+999999999'. Up to 15 digits allowed.")])),
        migrations.RunPython(add_country_prefix, migrations.RunPython.noop),
    ]
