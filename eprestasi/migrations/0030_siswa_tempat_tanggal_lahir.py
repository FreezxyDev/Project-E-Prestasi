from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('eprestasi', '0029_lupa_password'),
    ]

    operations = [
        migrations.AddField(
            model_name='siswa',
            name='tempat_lahir',
            field=models.CharField(blank=True, default='', max_length=100),
        ),
        migrations.AddField(
            model_name='siswa',
            name='tanggal_lahir',
            field=models.DateField(blank=True, null=True),
        ),
    ]
