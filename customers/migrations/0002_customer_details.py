from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('customers', '0001_initial'),
    ]

    operations = [
        # Keep existing data: the old single address becomes the present address.
        migrations.RenameField(model_name='customer', old_name='address', new_name='present_address'),
        migrations.AddField(
            model_name='customer', name='permanent_address',
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name='customer', name='date_of_birth',
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='customer', name='nationality',
            field=models.CharField(blank=True, default='Bangladeshi', max_length=50),
        ),
        migrations.AddField(
            model_name='customer', name='occupation',
            field=models.CharField(blank=True, max_length=100, verbose_name='Occupation / Profession'),
        ),
        migrations.AddField(
            model_name='customer', name='father_name',
            field=models.CharField(blank=True, max_length=150, verbose_name="Father's name"),
        ),
        migrations.AddField(
            model_name='customer', name='mother_name',
            field=models.CharField(blank=True, max_length=150, verbose_name="Mother's name"),
        ),
        migrations.AddField(
            model_name='customer', name='spouse_name',
            field=models.CharField(blank=True, max_length=150, verbose_name="Spouse's name"),
        ),
        migrations.AddField(
            model_name='customer', name='nominee_name',
            field=models.CharField(blank=True, max_length=150, verbose_name='Nominee name'),
        ),
        migrations.AddField(
            model_name='customer', name='nominee_relation',
            field=models.CharField(blank=True, max_length=50, verbose_name='Nominee relation'),
        ),
    ]
