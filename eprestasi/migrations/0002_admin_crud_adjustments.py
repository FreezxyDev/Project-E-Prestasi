from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('eprestasi', '0001_initial'),
    ]

    operations = [
        migrations.AlterField(
            model_name='siswa',
            name='email',
            field=models.EmailField(max_length=100, blank=True, null=True),
        ),
        migrations.AlterField(
            model_name='siswa',
            name='no_hp',
            field=models.CharField(max_length=100, blank=True, null=True),
        ),
        migrations.AlterField(
            model_name='siswa',
            name='nama',
            field=models.CharField(max_length=100, blank=True, default=''),
        ),
        migrations.AlterField(
            model_name='siswa',
            name='kelas',
            field=models.CharField(max_length=100, blank=True, default=''),
        ),
        migrations.AlterField(
            model_name='siswa',
            name='jurusan',
            field=models.CharField(
                max_length=100, blank=True, default='',
                choices=[('RPL', 'RPL'), ('TKJ', 'TKJ'), ('MPLB', 'MPLB'), ('PM', 'PM'), ('AKL', 'AKL')],
            ),
        ),
        migrations.AlterField(
            model_name='kesiswaan',
            name='nama',
            field=models.CharField(max_length=100, blank=True, default=''),
        ),
        migrations.AlterField(
            model_name='kesiswaan',
            name='nip',
            field=models.CharField(max_length=100, unique=True),
        ),
    ]
