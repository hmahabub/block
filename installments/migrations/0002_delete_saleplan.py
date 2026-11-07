from django.db import migrations


def tag_installment_payments(apps, schema_editor):
    """Installments used to be paid by whatever a customer paid after the first installment was issued. Now each payment says
    what it is for, so mark those payments as installment payments before the old bookkeeping is dropped."""
    SalePlan = apps.get_model('installments', 'SalePlan')
    CustomerPayment = apps.get_model('sales', 'CustomerPayment')
    for plan in SalePlan.objects.all():
        running = 0
        for payment in CustomerPayment.objects.filter(sale_id=plan.sale_id).order_by('payment_date', 'id'):
            if running >= plan.base:
                CustomerPayment.objects.filter(pk=payment.pk).update(purpose='INSTALLMENT')
            running += payment.amount


class Migration(migrations.Migration):

    dependencies = [
        ('installments', '0001_initial'),
        ('sales', '0006_customerpayment_installment_customerpayment_purpose'),
    ]

    operations = [
        migrations.RunPython(tag_installment_payments, migrations.RunPython.noop),
        migrations.DeleteModel(
            name='SalePlan',
        ),
    ]
