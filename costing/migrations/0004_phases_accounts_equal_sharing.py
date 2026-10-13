import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

PRE_CATEGORIES = {'land', 'marketing'}
EITHER_CATEGORIES = {'administration', 'administrative'}


def assign_phases(apps, schema_editor):
    """Land and Marketing are pre-development, Administration can be either, the rest is post-development.
    Existing costs take the phase of their category (admin costs default to post-development)."""
    CostCategory = apps.get_model('costing', 'CostCategory')
    ProjectCost = apps.get_model('costing', 'ProjectCost')

    for category in CostCategory.objects.filter(parent_category__isnull=True):
        name = category.name.strip().lower()
        phase = 'PRE' if name in PRE_CATEGORIES else 'EITHER' if name in EITHER_CATEGORIES else 'POST'
        CostCategory.objects.filter(pk=category.pk).update(phase=phase)
        CostCategory.objects.filter(parent_category=category).update(phase=phase)

    for cost in ProjectCost.objects.select_related('cost_category', 'cost_category__parent_category'):
        category = cost.cost_category
        phase = (category.parent_category.phase if category.parent_category_id else category.phase)
        ProjectCost.objects.filter(pk=cost.pk).update(phase='PRE' if phase == 'PRE' and cost.flat_id is None else 'POST')


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('books', '0003_merge_books_into_accounts'),
        ('projects', '0004_project_level_flat_specs'),
        ('costing', '0003_remove_projectcost_paid_amount_and_more'),
    ]

    operations = [
        migrations.AddField(model_name='costcategory', name='phase', field=models.CharField(
            choices=[('PRE', 'Pre-development'), ('POST', 'Post-development'), ('EITHER', 'Either (chosen on each entry)')],
            default='POST', help_text='Sub-categories always follow their parent category.', max_length=6)),
        migrations.AddField(model_name='projectcost', name='phase', field=models.CharField(
            choices=[('PRE', 'Pre-development'), ('POST', 'Post-development')], default='POST',
            help_text='Pre-development costs offset the share-sale profit; post-development costs are borne equally by all flat owners.',
            max_length=4)),
        migrations.RunPython(assign_phases, migrations.RunPython.noop),

        migrations.AddField(model_name='projectcost', name='account', field=models.ForeignKey(
            blank=True, help_text='The bank or cash account the money was paid from.', null=True,
            on_delete=django.db.models.deletion.PROTECT, related_name='costs', to='books.account', verbose_name='Paid from')),
        migrations.AddField(model_name='projectcost', name='confirmed_at', field=models.DateTimeField(blank=True, editable=False, null=True)),
        migrations.AddField(model_name='projectcost', name='confirmed_by', field=models.ForeignKey(
            blank=True, editable=False, null=True, on_delete=django.db.models.deletion.SET_NULL,
            related_name='+', to=settings.AUTH_USER_MODEL)),

        # Post-development costs are now shared equally by flat count, so the stored area-based rows go.
        migrations.DeleteModel(name='CostAllocation'),
        migrations.RemoveField(model_name='projectcost', name='allocation_required'),
        migrations.AlterField(model_name='projectcost', name='flat', field=models.ForeignKey(
            blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='project_costs',
            to='projects.flat',
            help_text='Leave blank for a shared project cost, borne equally by every flat in the project. '
                      'Set it only for a cost that belongs to one flat.')),
    ]
