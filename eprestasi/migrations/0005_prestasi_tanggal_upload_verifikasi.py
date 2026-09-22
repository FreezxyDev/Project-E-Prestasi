import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('eprestasi', '0004_prestasi_alasan_penolakan'),
    ]

    operations = [
        migrations.AddField(
            model_name='prestasi',
            name='tanggal_upload',
            # default dipakai HANYA untuk mengisi baris-baris LAMA yang sudah ada
            # di database (supaya tidak error karena field ini wajib/not-null).
            # Baris BARU setelah migration ini tetap otomatis pakai waktu asli
            # saat itu dibuat, karena auto_now_add=True.
            field=models.DateTimeField(auto_now_add=True, default=django.utils.timezone.now),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='prestasi',
            name='tanggal_verifikasi',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
