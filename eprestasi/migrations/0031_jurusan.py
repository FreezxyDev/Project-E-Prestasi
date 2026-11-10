from django.db import migrations, models


def isi_jurusan_awal(apps, schema_editor):
    Jurusan = apps.get_model('eprestasi', 'Jurusan')
    for kode in ['RPL', 'TKJ', 'DKV', 'MPLB', 'AKL', 'PM']:
        Jurusan.objects.get_or_create(kode=kode)


class Migration(migrations.Migration):

    dependencies = [
        ('eprestasi', '0030_siswa_tempat_tanggal_lahir'),
    ]

    operations = [
        migrations.CreateModel(
            name='Jurusan',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('kode', models.CharField(max_length=10, unique=True)),
            ],
            options={
                'db_table': 'jurusan',
                'ordering': ['id'],
            },
        ),
        migrations.RunPython(isi_jurusan_awal, migrations.RunPython.noop),
    ]
