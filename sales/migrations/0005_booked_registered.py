from django.db import migrations, models


def sold_becomes_booked(apps, schema_editor):
    apps.get_model('sales', 'FlatSale').objects.filter(status='SOLD').update(status='BOOKED')


def booked_becomes_sold(apps, schema_editor):
    apps.get_model('sales', 'FlatSale').objects.filter(status__in=['BOOKED', 'REGISTERED']).update(status='SOLD')


class Migration(migrations.Migration):
    """A sale is Booked until its registry is completed, then Registered; it can be Cancelled before that."""

    dependencies = [
        ('sales', '0004_parking_sale_value'),
    ]

    operations = [
        migrations.AddField(
            model_name='flatsale', name='registered_on',
            field=models.DateField(
                blank=True, editable=False, null=True,
                help_text='The day the registry was completed and the flat registered to the owner.',
            ),
        ),
        migrations.RunPython(sold_becomes_booked, booked_becomes_sold),
        migrations.AlterField(
            model_name='flatsale', name='status',
            field=models.CharField(
                choices=[('BOOKED', 'Booked'), ('REGISTERED', 'Registered'), ('CANCELLED', 'Cancelled')],
                default='BOOKED', max_length=10,
            ),
        ),
    ]
