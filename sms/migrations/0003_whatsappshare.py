import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('customers', '0003_title_whatsapp_emergency_tin_sms'),
        ('sales', '0003_remove_booked_status'),
        ('sms', '0002_smslog_gateway_id'),
    ]

    operations = [
        migrations.CreateModel(
            name='WhatsAppShare',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('phone', models.CharField(max_length=20, verbose_name='WhatsApp no.')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('customer', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='whatsapp_shares', to='customers.customer')),
                ('opened_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('sale', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='whatsapp_shares', to='sales.flatsale')),
            ],
            options={'verbose_name': 'WhatsApp invoice', 'ordering': ['-created_at', '-id']},
        ),
    ]
