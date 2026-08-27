from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('eprestasi', '0003_role_super_admin'),
    ]

    operations = [
        migrations.AddField(
            model_name='prestasi',
            name='alasan_penolakan',
            field=models.TextField(blank=True, null=True),
        ),
    ]
