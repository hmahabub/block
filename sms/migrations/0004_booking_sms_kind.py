from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('sms', '0003_whatsappshare'),
    ]

    operations = [
        migrations.AlterField(
            model_name='smslog', name='kind',
            field=models.CharField(
                choices=[('PAYMENT', 'Payment confirmation'), ('BOOKING', 'Booking confirmation'), ('REMINDER', 'Balance reminder')],
                max_length=10),
        ),
    ]
