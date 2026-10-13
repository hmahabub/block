import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('customers', '0003_title_whatsapp_emergency_tin_sms'),
    ]

    operations = [
        migrations.CreateModel(
            name='SmsLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('phone', models.CharField(max_length=20)),
                ('kind', models.CharField(choices=[('PAYMENT', 'Payment confirmation'), ('REMINDER', 'Balance reminder')], max_length=10)),
                ('message', models.TextField()),
                ('status', models.CharField(choices=[('SENT', 'Sent'), ('LOGGED', 'Logged only (no gateway configured)'), ('FAILED', 'Failed')], max_length=10)),
                ('error', models.CharField(blank=True, max_length=300)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('customer', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='sms_logs', to='customers.customer')),
                ('sent_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
            ],
            options={'verbose_name': 'SMS', 'ordering': ['-created_at', '-id']},
        ),
    ]
