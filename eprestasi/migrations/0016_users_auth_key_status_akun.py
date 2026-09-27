import uuid
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('eprestasi', '0015_alter_prestasi_kategori_prestasi'),
    ]

    operations = [
        migrations.AddField(
            model_name='users',
            name='auth_key',
            field=models.UUIDField(default=uuid.uuid4, editable=False),
        ),
        migrations.AddField(
            model_name='users',
            name='status_akun',
            field=models.CharField(
                choices=[('aktif', 'aktif'), ('nonaktif', 'nonaktif')],
                default='aktif',
                max_length=20,
            ),
        ),
    ]
