from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('sms', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='smslog', name='gateway_id',
            field=models.CharField(blank=True, max_length=100, verbose_name='Gateway message id'),
        ),
    ]
