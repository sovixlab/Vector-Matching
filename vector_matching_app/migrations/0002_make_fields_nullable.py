# Generated manually to fix null constraint violations

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('vector_matching_app', '0001_initial'),
    ]

    operations = [
        migrations.AlterField(
            model_name='candidate',
            name='name',
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
        migrations.AlterField(
            model_name='candidate',
            name='email',
            field=models.EmailField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name='candidate',
            name='phone',
            field=models.CharField(blank=True, max_length=20, null=True),
        ),
        migrations.AlterField(
            model_name='candidate',
            name='street',
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
        migrations.AlterField(
            model_name='candidate',
            name='house_number',
            field=models.CharField(blank=True, max_length=10, null=True),
        ),
        migrations.AlterField(
            model_name='candidate',
            name='postal_code',
            field=models.CharField(blank=True, max_length=10, null=True),
        ),
        migrations.AlterField(
            model_name='candidate',
            name='city',
            field=models.CharField(blank=True, max_length=100, null=True),
        ),
    ]
