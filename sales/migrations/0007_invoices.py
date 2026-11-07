import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


def create_invoices(apps, schema_editor):
    """Every existing booking gets its booking invoice, every installment charge its invoice, and every payment is put
    under the invoice it paid (an installment payment under the installment it named, else the earliest one; the rest under
    the booking invoice)."""
    FlatSale = apps.get_model('sales', 'FlatSale')
    Invoice = apps.get_model('sales', 'Invoice')
    CustomerPayment = apps.get_model('sales', 'CustomerPayment')
    InstallmentCharge = apps.get_model('installments', 'InstallmentCharge')

    for sale in FlatSale.objects.all():
        booking = Invoice.objects.create(sale=sale, kind='BOOKING', issued_on=sale.sale_date)
        by_installment, charges = {}, []
        for charge in InstallmentCharge.objects.filter(sale_id=sale.pk).select_related('installment').order_by('installment__due_date', 'id'):
            invoice = Invoice.objects.create(sale=sale, kind='INSTALLMENT', charge=charge, issued_on=charge.installment.issued_on)
            by_installment[charge.installment_id] = invoice
            charges.append(invoice)
        for payment in CustomerPayment.objects.filter(sale_id=sale.pk):
            target = booking
            if payment.purpose == 'INSTALLMENT' and charges:
                target = by_installment.get(payment.installment_id) or charges[0]
            CustomerPayment.objects.filter(pk=payment.pk).update(invoice=target)


class Migration(migrations.Migration):

    dependencies = [
        ('installments', '0002_delete_saleplan'),
        ('sales', '0006_customerpayment_installment_customerpayment_purpose'),
    ]

    operations = [
        migrations.CreateModel(
            name='Invoice',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('kind', models.CharField(choices=[('BOOKING', 'Flat booking'), ('INSTALLMENT', 'Installment')], max_length=12)),
                ('issued_on', models.DateField(default=django.utils.timezone.localdate)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('charge', models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='invoice', to='installments.installmentcharge')),
                ('sale', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='invoices', to='sales.flatsale')),
            ],
            options={
                'ordering': ['issued_on', 'id'],
            },
        ),
        migrations.AddConstraint(
            model_name='invoice',
            constraint=models.UniqueConstraint(condition=models.Q(('kind', 'BOOKING')), fields=('sale',), name='one_booking_invoice_per_sale'),
        ),
        migrations.AddField(
            model_name='customerpayment',
            name='invoice',
            field=models.ForeignKey(help_text='The invoice this payment settles: the flat booking, or an installment.', null=True, on_delete=django.db.models.deletion.RESTRICT, related_name='payments', to='sales.invoice', verbose_name='Paid under invoice'),
        ),
        migrations.RunPython(create_invoices, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name='customerpayment',
            name='installment',
        ),
        migrations.RemoveField(
            model_name='customerpayment',
            name='purpose',
        ),
        migrations.AlterField(
            model_name='customerpayment',
            name='invoice',
            field=models.ForeignKey(help_text='The invoice this payment settles: the flat booking, or an installment.', on_delete=django.db.models.deletion.RESTRICT, related_name='payments', to='sales.invoice', verbose_name='Paid under invoice'),
        ),
    ]
