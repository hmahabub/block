from django.db import migrations, models


def booked_becomes_sold(apps, schema_editor):
    apps.get_model('projects', 'Flat').objects.filter(status='BOOKED').update(status='SOLD')


class Migration(migrations.Migration):
    """There is no "Booked" status any more: a flat that has a customer is Sold."""

    dependencies = [
        ('projects', '0004_project_level_flat_specs'),
    ]

    operations = [
        migrations.RunPython(booked_becomes_sold, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='flat', name='status',
            field=models.CharField(
                choices=[('AVAILABLE', 'Available'), ('SOLD', 'Sold')], default='AVAILABLE', editable=False, max_length=20),
        ),
    ]
