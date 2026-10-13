import re

import django.core.validators
from django.db import migrations, models

PHONE = django.core.validators.RegexValidator(
    regex='^\\+?1?\\d{9,15}$', message="Phone number must be in format: '+999999999'. Up to 15 digits allowed.")


def add_country_prefix(apps, schema_editor):
    """Give every existing local number the +88 prefix, skipping any that would collide with another customer."""
    Customer = apps.get_model('customers', 'Customer')
    taken = set(Customer.objects.values_list('phone', flat=True))
    for customer in Customer.objects.all():
        number = re.sub(r'[\s\-().]', '', customer.phone or '')
        if number.startswith('+'):
            continue
        if number.startswith('0088'):
            new = '+' + number[2:]
        elif number.startswith('88') and len(number) >= 13:
            new = '+' + number
        else:
            new = '+88' + number
        if new == customer.phone or new in taken or len(new) > 17:
            continue
        taken.discard(customer.phone)
        taken.add(new)
        Customer.objects.filter(pk=customer.pk).update(phone=new)


class Migration(migrations.Migration):

    dependencies = [
        ('customers', '0002_customer_details'),
    ]

    operations = [
        migrations.AddField(model_name='customer', name='title', field=models.CharField(
            blank=True, choices=[('MR', 'Mr.'), ('MS', 'Ms.')], max_length=2)),
        migrations.AddField(model_name='customer', name='whatsapp_no', field=models.CharField(
            blank=True, max_length=17, validators=[PHONE], verbose_name='WhatsApp no.')),
        migrations.AddField(model_name='customer', name='tin', field=models.CharField(blank=True, max_length=30, verbose_name='TIN')),
        migrations.AddField(model_name='customer', name='emergency_contact_name', field=models.CharField(
            blank=True, max_length=150, verbose_name='Emergency contact name')),
        migrations.AddField(model_name='customer', name='emergency_contact_phone', field=models.CharField(
            blank=True, max_length=17, validators=[PHONE], verbose_name='Emergency contact no.')),
        migrations.AddField(model_name='customer', name='sms_enabled', field=models.BooleanField(
            default=True, help_text='Untick to exclude this customer from every SMS (payment confirmations and reminders).',
            verbose_name='Send SMS')),
        migrations.AlterField(model_name='customer', name='phone', field=models.CharField(
            help_text='+88 is added automatically to local numbers.', max_length=17, unique=True, validators=[PHONE])),
        migrations.RunPython(add_country_prefix, migrations.RunPython.noop),
    ]
