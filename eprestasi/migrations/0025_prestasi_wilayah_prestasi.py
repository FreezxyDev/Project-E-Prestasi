from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('eprestasi', '0024_siswa_alamat_alter_siswa_kelas'),
    ]

    operations = [
        migrations.AddField(
            model_name='prestasi',
            name='wilayah_prestasi',
            field=models.CharField(
                choices=[('dalam_negeri', 'Dalam Negeri'), ('luar_negeri', 'Luar Negeri')],
                default='dalam_negeri',
                max_length=20,
            ),
        ),
    ]
