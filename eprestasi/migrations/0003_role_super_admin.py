from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('eprestasi', '0002_admin_crud_adjustments'),
    ]

    operations = [
        migrations.AlterField(
            model_name='users',
            name='role',
            field=models.CharField(max_length=100, choices=[
                ('super_admin', 'super_admin'),
                ('admin', 'admin'),
                ('siswa', 'siswa'),
                ('kesiswaan', 'kesiswaan'),
            ]),
        ),
    ]
