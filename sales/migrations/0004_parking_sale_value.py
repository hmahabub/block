from django.core.validators import MinValueValidator
from django.db import migrations, models


def split_existing_sales(apps, schema_editor):
    """Sales made before the split: the parking lot is taken at its price, the rest of the sale value is the flat."""
    FlatSale = apps.get_model('sales', 'FlatSale')
    for sale in FlatSale.objects.filter(with_parking=True, parking_price__gt=0):
        FlatSale.objects.filter(pk=sale.pk).update(parking_sale_value=min(sale.parking_price, sale.sale_value))


class Migration(migrations.Migration):

    dependencies = [
        ('sales', '0003_remove_booked_status'),
    ]

    operations = [
        migrations.AddField(
            model_name='flatsale', name='parking_sale_value',
            field=models.DecimalField(
                decimal_places=2, default=0, max_digits=14, validators=[MinValueValidator(0)],
                help_text='What the customer pays for the parking lot (only when parking is taken). Part of the sale value.',
            ),
        ),
        migrations.AlterField(
            model_name='flatsale', name='sale_value',
            field=models.DecimalField(
                decimal_places=2, default=0, max_digits=14, validators=[MinValueValidator(0)],
                help_text='Flat sale value + parking sale value.',
            ),
        ),
        migrations.RunPython(split_existing_sales, migrations.RunPython.noop),
    ]
