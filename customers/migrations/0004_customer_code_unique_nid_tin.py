from django.db import migrations, models


def tidy_and_check_duplicates(apps, schema_editor):
    """NID and TIN become unique. Strip stray spaces first, then stop with a clear list if two customers still share one,
    so nothing is changed or lost silently: fix the listed customers, then run the migration again."""
    Customer = apps.get_model('customers', 'Customer')
    for customer in Customer.objects.all():
        nid, tin = customer.identification_no.strip(), customer.tin.strip()
        if (nid, tin) != (customer.identification_no, customer.tin):
            Customer.objects.filter(pk=customer.pk).update(identification_no=nid, tin=tin)

    problems = []
    for field, label in (('identification_no', 'NID / passport no.'), ('tin', 'TIN')):
        seen = {}
        for customer in Customer.objects.exclude(**{field: ''}).order_by('id'):
            seen.setdefault(getattr(customer, field), []).append(customer)
        for value, customers in seen.items():
            if len(customers) > 1:
                names = ', '.join(f'{c.name} (id {c.pk}, {c.phone})' for c in customers)
                problems.append(f'{label} {value} is shared by: {names}')
    if problems:
        raise RuntimeError(
            'Cannot make NID / TIN unique yet. Give each of these customers their own number (or clear the field), '
            'then run "python manage.py migrate" again:\n  - ' + '\n  - '.join(problems)
        )


def give_every_customer_an_id(apps, schema_editor):
    """C0001, C0002 ... in the order the customers were created; the counter continues from the last one."""
    Customer = apps.get_model('customers', 'Customer')
    Sequence = apps.get_model('core', 'Sequence')
    number = 0
    for customer in Customer.objects.order_by('id'):
        number += 1
        Customer.objects.filter(pk=customer.pk).update(customer_code=f'C{number:04d}')
    sequence, _ = Sequence.objects.get_or_create(key='customer:C')
    sequence.last_number = number
    sequence.save()


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0002_companyprofile'),
        ('customers', '0003_title_whatsapp_emergency_tin_sms'),
    ]

    operations = [
        migrations.RunPython(tidy_and_check_duplicates, migrations.RunPython.noop),
        migrations.AddField(
            model_name='customer', name='customer_code',
            field=models.CharField(editable=False, max_length=10, null=True, verbose_name='Customer ID'),
        ),
        migrations.RunPython(give_every_customer_an_id, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='customer', name='customer_code',
            field=models.CharField(editable=False, max_length=10, unique=True, verbose_name='Customer ID'),
        ),
        migrations.AlterField(
            model_name='customer', name='identification_no',
            field=models.CharField(blank=True, help_text='Must be unique: two customers cannot share an NID / passport number.',
                                   max_length=50, verbose_name='NID / Passport No.'),
        ),
        migrations.AlterField(
            model_name='customer', name='tin',
            field=models.CharField(blank=True, help_text='Must be unique when given.', max_length=30, verbose_name='TIN'),
        ),
        migrations.AddConstraint(
            model_name='customer',
            constraint=models.UniqueConstraint(
                condition=models.Q(('identification_no', ''), _negated=True), fields=('identification_no',),
                name='customer_nid_unique_when_given'),
        ),
        migrations.AddConstraint(
            model_name='customer',
            constraint=models.UniqueConstraint(
                condition=models.Q(('tin', ''), _negated=True), fields=('tin',), name='customer_tin_unique_when_given'),
        ),
    ]
