from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ('eprestasi', '0028_siswa_keluar'),
    ]

    operations = [
        migrations.CreateModel(
            name='PermintaanResetPassword',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('alasan', models.CharField(blank=True, default='', max_length=30)),
                ('status', models.CharField(choices=[('pending', 'Menunggu'), ('selesai', 'Selesai'), ('ditolak', 'Ditolak')], default='pending', max_length=10)),
                ('dibuat_pada', models.DateTimeField(auto_now_add=True)),
                ('diproses_pada', models.DateTimeField(blank=True, null=True)),
                ('diproses_oleh', models.CharField(blank=True, default='', max_length=100)),
                ('catatan', models.CharField(blank=True, default='', max_length=255)),
                ('siswa', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='permintaan_reset_password', to='eprestasi.siswa')),
            ],
            options={
                'db_table': 'permintaan_reset_password',
                'ordering': ['-dibuat_pada'],
            },
        ),
        migrations.CreateModel(
            name='OtpResetPassword',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('kanal', models.CharField(choices=[('email', 'Email'), ('hp', 'No HP')], max_length=10)),
                ('tujuan', models.CharField(max_length=100)),
                ('kode_hash', models.CharField(max_length=64)),
                ('dibuat_pada', models.DateTimeField(default=django.utils.timezone.now)),
                ('kedaluwarsa_pada', models.DateTimeField()),
                ('terpakai', models.BooleanField(default=False)),
                ('percobaan_salah', models.PositiveSmallIntegerField(default=0)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='otp_reset_password', to='eprestasi.users')),
            ],
            options={
                'db_table': 'otp_reset_password',
                'ordering': ['-dibuat_pada'],
            },
        ),
    ]
