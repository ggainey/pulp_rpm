# Generated by Django 2.2.14 on 2020-08-06 00:58

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('rpm', '0021_rename_updatecollection_update_record'),
    ]

    operations = [
        migrations.AlterField(
            model_name='updatecollection',
            name='update_record',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='collections', to='rpm.UpdateRecord'),
        ),
        migrations.AlterUniqueTogether(
            name='updatecollection',
            unique_together={('name', 'update_record')},
        ),
    ]
