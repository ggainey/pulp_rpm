# Generated by Django 2.2.17 on 2020-12-14 22:12

from django.db import migrations, models


def set_true(apps, schema_editor):
    Publication = apps.get_model("rpm", "RpmPublication")
    Publication.objects.update(sqlite_metadata=True)

class Migration(migrations.Migration):

    dependencies = [
        ('rpm', '0028_rpmrepository_last_sync_repomd_cheksum'),
    ]

    operations = [
        migrations.AddField(
            model_name='rpmpublication',
            name='sqlite_metadata',
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(set_true)
    ]
