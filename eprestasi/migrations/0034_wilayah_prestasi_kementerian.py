"""
Wilayah prestasi kini berbasis Kementerian Pendidikan (didalam / diluar).

- Melebarkan kolom prestasi.wilayah_prestasi dari varchar(20) menjadi varchar(50). Nilai baru
  ('didalam_kementrian_pendidikan' = 29 karakter) TIDAK muat di varchar(20): itu penyebab error
  "value too long for type character varying(20)" saat upload prestasi.
- Data lama ('dalam_negeri' / 'luar_negeri') dibiarkan apa adanya; hanya ditampilkan sebagai "(data lama)".
"""
from django.db import migrations, models

PILIHAN = [
    ('didalam_kementrian_pendidikan', 'Didalam Kementrian Pendidikan'),
    ('diluar_kementrian_pendidikan', 'Diluar Kementrian Pendidikan'),
    ('dalam_negeri', 'Dalam Negeri (data lama)'),
    ('luar_negeri', 'Luar Negeri (data lama)'),
]


class Migration(migrations.Migration):

    dependencies = [
        ('eprestasi', '0033_merge_0031_jurusan_0032_seed_kategori_prestasi'),
    ]

    operations = [
        migrations.AlterField(
            model_name='prestasi',
            name='wilayah_prestasi',
            field=models.CharField(choices=PILIHAN, default='didalam_kementrian_pendidikan', max_length=50),
        ),
        migrations.AlterField(
            model_name='prestasi',
            name='jenis_wilayah_puspresnas',
            field=models.CharField(blank=True, choices=PILIHAN, max_length=50, null=True),
        ),
    ]
