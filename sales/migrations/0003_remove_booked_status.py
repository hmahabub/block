from django.db import migrations, models


def booked_becomes_sold(apps, schema_editor):
    apps.get_model('sales', 'FlatSale').objects.filter(status='BOOKED').update(status='SOLD')


class Migration(migrations.Migration):
    """There is no "Booked" status any more: a sale is Sold from the moment it is made, until it is cancelled."""

    dependencies = [
        ('sales', '0002_sale_value_honorarium_refunds'),
    ]

    operations = [
        migrations.RunPython(booked_becomes_sold, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='flatsale', name='status',
            field=models.CharField(choices=[('SOLD', 'Sold'), ('CANCELLED', 'Cancelled')], default='SOLD', max_length=10),
        ),
    ]
