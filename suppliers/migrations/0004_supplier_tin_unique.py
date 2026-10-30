from django.db import migrations, models


def tidy_and_check_duplicates(apps, schema_editor):
    Supplier = apps.get_model('suppliers', 'Supplier')
    for supplier in Supplier.objects.all():
        if supplier.tin != supplier.tin.strip():
            Supplier.objects.filter(pk=supplier.pk).update(tin=supplier.tin.strip())
    seen = {}
    for supplier in Supplier.objects.exclude(tin='').order_by('id'):
        seen.setdefault(supplier.tin, []).append(supplier)
    problems = [
        f'TIN {tin} is shared by: ' + ', '.join(f'{s.name} ({s.supplier_code})' for s in suppliers)
        for tin, suppliers in seen.items() if len(suppliers) > 1
    ]
    if problems:
        raise RuntimeError(
            'Cannot make the supplier TIN unique yet. Give each of these suppliers their own TIN (or clear it), '
            'then run "python manage.py migrate" again:\n  - ' + '\n  - '.join(problems)
        )


class Migration(migrations.Migration):

    dependencies = [
        ('suppliers', '0003_supplier_tin'),
    ]

    operations = [
        migrations.RunPython(tidy_and_check_duplicates, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name='supplier',
            constraint=models.UniqueConstraint(
                condition=models.Q(('tin', ''), _negated=True), fields=('tin',), name='supplier_tin_unique_when_given'),
        ),
    ]
