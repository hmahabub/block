from django.db import migrations, models


def sold_becomes_booked(apps, schema_editor):
    apps.get_model('projects', 'Flat').objects.filter(status='SOLD').update(status='BOOKED')


def booked_becomes_sold(apps, schema_editor):
    apps.get_model('projects', 'Flat').objects.filter(status__in=['BOOKED', 'REGISTERED']).update(status='SOLD')


class Migration(migrations.Migration):
    """A flat is Available, Booked (sold, registry not done yet) or Registered (registry completed)."""

    dependencies = [
        ('projects', '0007_flat_parking_price'),
    ]

    operations = [
        migrations.RunPython(sold_becomes_booked, booked_becomes_sold),
        migrations.AlterField(
            model_name='flat', name='status',
            field=models.CharField(
                choices=[('AVAILABLE', 'Available'), ('BOOKED', 'Booked'), ('REGISTERED', 'Registered')],
                default='AVAILABLE', editable=False, max_length=20,
            ),
        ),
    ]
