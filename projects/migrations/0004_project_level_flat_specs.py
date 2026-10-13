import re

import django.core.validators
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def move_specs_to_projects_and_renumber(apps, schema_editor):
    """Flats are identical within a project, so lift their shared spec onto the project and
    renumber flats to the letter-plus-floor format (A1) wherever that is unambiguous.

    Flats whose number cannot be converted safely are left exactly as they were (no unit), so no
    existing flat is ever renamed to something that could collide or lose meaning.
    """
    Project = apps.get_model('projects', 'Project')
    Flat = apps.get_model('projects', 'Flat')

    for project in Project.objects.all():
        first = Flat.objects.filter(project=project).order_by('id').first()
        if first:
            project.flat_type = first.flat_type
            project.flat_area = first.saleable_area
            project.base_price = first.base_price
            project.quoted_price = first.base_price
            project.bedrooms = first.bedrooms
            project.bathrooms = first.bathrooms
            project.parking_area = first.parking_area
            project.features = first.features
            project.save()

        used = set(Flat.objects.filter(project=project).values_list('flat_no', flat=True))
        for flat in Flat.objects.filter(project=project).order_by('floor_no', 'id'):
            unit = ''
            if re.fullmatch(r'\d+', flat.flat_no):
                position = int(flat.flat_no) - flat.floor_no * 100
                if 1 <= position <= 26:
                    unit = chr(64 + position)
            else:
                match = re.fullmatch(r'([A-Za-z])(\d+)', flat.flat_no)
                if match and int(match.group(2)) == flat.floor_no:
                    unit = match.group(1).upper()

            flat_no = flat.flat_no
            if unit:
                candidate = f'{unit}{flat.floor_no}'
                if candidate == flat.flat_no or candidate not in used:
                    used.discard(flat.flat_no)
                    used.add(candidate)
                    flat_no = candidate
                else:
                    unit = ''
            Flat.objects.filter(pk=flat.pk).update(unit=unit, flat_no=flat_no, parking_lot=f'P-{flat_no}'[:20])


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('projects', '0003_flat_bathrooms_flat_bedrooms_flat_features_and_more'),
    ]

    operations = [
        # --- project-level flat specification and prices
        migrations.AddField(model_name='project', name='flat_type', field=models.CharField(
            choices=[('STUDIO', 'Studio'), ('1BED', '1 Bedroom'), ('2BED', '2 Bedroom'), ('3BED', '3 Bedroom'),
                     ('4BED', '4 Bedroom'), ('DUPLEX', 'Duplex'), ('PENTHOUSE', 'Penthouse'),
                     ('COMMERCIAL', 'Commercial'), ('OTHER', 'Other')],
            default='2BED', max_length=20)),
        migrations.AddField(model_name='project', name='flat_area', field=models.DecimalField(
            decimal_places=2, default=0, max_digits=10, verbose_name='Saleable area per flat (sqft)')),
        migrations.AddField(model_name='project', name='bedrooms', field=models.PositiveSmallIntegerField(blank=True, null=True)),
        migrations.AddField(model_name='project', name='bathrooms', field=models.PositiveSmallIntegerField(blank=True, null=True)),
        migrations.AddField(model_name='project', name='features', field=models.CharField(
            blank=True, help_text='e.g. Drawing, Dining, Balcony', max_length=255, verbose_name='Rooms & features')),
        migrations.AddField(model_name='project', name='base_price', field=models.DecimalField(
            decimal_places=2, default=0, max_digits=14, validators=[django.core.validators.MinValueValidator(0)],
            help_text='What the company needs from each flat share. Anything a buyer pays above it is the reference honorarium.',
            verbose_name='Base price per flat')),
        migrations.AddField(model_name='project', name='quoted_price', field=models.DecimalField(
            decimal_places=2, default=0, max_digits=14, validators=[django.core.validators.MinValueValidator(0)],
            help_text='The price quoted to buyers; it pre-fills the sale value.', verbose_name='Quoted price per flat')),
        migrations.AddField(model_name='project', name='parking_price', field=models.DecimalField(
            decimal_places=2, default=0, max_digits=14, validators=[django.core.validators.MinValueValidator(0)],
            help_text='Extra price when the buyer takes the parking lot linked to the flat.', verbose_name='Parking lot price')),
        migrations.AddField(model_name='project', name='parking_area', field=models.DecimalField(
            blank=True, decimal_places=2, max_digits=8, null=True, verbose_name='Parking lot area (sqft)')),

        # --- flat numbering: unit letter + floor, and the linked parking lot
        migrations.AddField(model_name='flat', name='unit', field=models.CharField(
            blank=True, help_text='Flat unit letter, e.g. A', max_length=1,
            validators=[django.core.validators.RegexValidator('^[A-Z]$', 'Use a single capital letter, for example A.')])),
        migrations.AddField(model_name='flat', name='parking_lot', field=models.CharField(
            blank=True, help_text='Parking lot linked to this flat. Defaults to P-<flat no.>.', max_length=20)),

        migrations.RunPython(move_specs_to_projects_and_renumber, migrations.RunPython.noop),

        # --- the per-flat copies of the spec are gone; flats read them from the project
        migrations.RemoveField(model_name='flat', name='flat_type'),
        migrations.RemoveField(model_name='flat', name='saleable_area'),
        migrations.RemoveField(model_name='flat', name='base_price'),
        migrations.RemoveField(model_name='flat', name='bedrooms'),
        migrations.RemoveField(model_name='flat', name='bathrooms'),
        migrations.RemoveField(model_name='flat', name='parking_area'),
        migrations.RemoveField(model_name='flat', name='features'),
        migrations.RemoveField(model_name='project', name='total_saleable_area'),

        migrations.AlterField(model_name='flat', name='floor_no', field=models.PositiveSmallIntegerField()),
        migrations.AlterField(model_name='flat', name='flat_no', field=models.CharField(editable=False, max_length=30)),
        migrations.AlterField(model_name='flat', name='project', field=models.ForeignKey(
            on_delete=django.db.models.deletion.PROTECT, related_name='flats', to='projects.project')),
        migrations.AlterModelOptions(name='flat', options={
            'ordering': ['project', 'floor_no', 'unit', 'flat_no'],
            'permissions': [('approve_flat_deletion', 'Can approve flat deletion requests')],
        }),

        migrations.CreateModel(
            name='FlatDeletionRequest',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('flat_label', models.CharField(max_length=120)),
                ('reason', models.TextField(blank=True)),
                ('status', models.CharField(
                    choices=[('PENDING', 'Waiting for a second admin'), ('APPROVED', 'Approved and deleted'),
                             ('REJECTED', 'Rejected'), ('CANCELLED', 'Withdrawn')],
                    default='PENDING', max_length=10)),
                ('requested_at', models.DateTimeField(auto_now_add=True)),
                ('decided_at', models.DateTimeField(blank=True, null=True)),
                ('decision_note', models.CharField(blank=True, max_length=300)),
                ('decided_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('flat', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='deletion_requests', to='projects.flat')),
                ('requested_by', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['-requested_at']},
        ),
    ]
