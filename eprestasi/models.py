from django.db import models
from cloudinary.models import CloudinaryField

# Create your models here
class Users(models.Model):
    username = models.CharField(max_length=100)
    password = models.CharField(max_length=100)
    role = models.CharField(max_length=100, choices=[
        ('super_admin', 'super_admin'),
        ('admin', 'admin'),
        ('siswa', 'siswa'),
        ('kesiswaan', 'kesiswaan'),
    ])
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'users'
        
    def __str__(self):
        return self.username
    
class Siswa(models.Model):
    users = models.ForeignKey(Users, on_delete=models.CASCADE)
    nis = models.CharField(max_length=100, unique=True)
    tingkat = models.PositiveSmallIntegerField(default=10)
    status = models.CharField(max_length=100, choices=[('aktif','aktif'), ('alumni','alumni')], default='aktif')
    nama = models.CharField(max_length=100, blank=True, default='')
    KELAS_CHOICES = [
        # Kelas X
        ('X PPLG 1', 'X PPLG 1'),
        ('X PPLG 2', 'X PPLG 2'),
        ('X DKV 1', 'X DKV 1'),
        ('X DKV 2', 'X DKV 2'),
        ('X TJKT 1', 'X TJKT 1'),
        ('X PM 1', 'X PM 1'),
        ('X PM 2', 'X PM 2'),
        ('X PM 3', 'X PM 3'),
        ('X MP 1', 'X MP 1'),
        ('X MP 2', 'X MP 2'),
        ('X MP 3', 'X MP 3'),
        ('X MP 4', 'X MP 4'),
        ('X MP 5', 'X MP 5'),
        ('X AKL 1', 'X AKL 1'),
        ('X AKL 2', 'X AKL 2'),
        ('X AKL 3', 'X AKL 3'),
        ('X AKL 4', 'X AKL 4'),

        # Kelas XI
        ('XI RPL 1', 'XI RPL 1'),
        ('XI RPL 2', 'XI RPL 2'),
        ('XI DKV 1', 'XI DKV 1'),
        ('XI DKV 2', 'XI DKV 2'),
        ('XI TJKT 1', 'XI TJKT 1'),
        ('XI PM 1', 'XI PM 1'),
        ('XI PM 2', 'XI PM 2'),
        ('XI PM 3', 'XI PM 3'),
        ('XI MP 1', 'XI MP 1'),
        ('XI MP 2', 'XI MP 2'),
        ('XI MP 3', 'XI MP 3'),
        ('XI MP 4', 'XI MP 4'),
        ('XI MP 5', 'XI MP 5'),
        ('XI AKL 1', 'XI AKL 1'),
        ('XI AKL 2', 'XI AKL 2'),
        ('XI AKL 3', 'XI AKL 3'),
        ('XI AKL 4', 'XI AKL 4'),

        # Kelas XII
        ('XII RPL 1', 'XII RPL 1'),
        ('XII RPL 2', 'XII RPL 2'),
        ('XII DKV 1', 'XII DKV 1'),
        ('XII DKV 2', 'XII DKV 2'),
        ('XII TJKT 1', 'XII TJKT 1'),
        ('XII PM 1', 'XII PM 1'),
        ('XII PM 2', 'XII PM 2'),
        ('XII PM 3', 'XII PM 3'),
        ('XII MP 1', 'XII MP 1'),
        ('XII MP 2', 'XII MP 2'),
        ('XII MP 3', 'XII MP 3'),
        ('XII MP 4', 'XII MP 4'),
        ('XII MP 5', 'XII MP 5'),
        ('XII AKL 1', 'XII AKL 1'),
        ('XII AKL 2', 'XII AKL 2'),
        ('XII AKL 3', 'XII AKL 3'),
        ('XII AKL 4', 'XII AKL 4'),
    ]    
    kelas = models.CharField(max_length=100, blank=True, null=True, choices=KELAS_CHOICES )
    JURUSAN_CHOICES = [
        ('RPL', 'RPL'),
        ('DKV', 'DKV'),
        ('TJKT', 'TJKT'),
        ('AKL', 'AKL'),
        ('MPLB', 'MPLB'),
        ('PM', 'PM'),
    ]
    jurusan = models.CharField(max_length=100, blank=True, null=True, choices = JURUSAN_CHOICES)
    email = models.EmailField(max_length=100, blank=True, null=True)
    no_hp = models.CharField(max_length=100, blank=True, null=True)
    foto_profil = CloudinaryField('foto_profil', blank=True, null=True)
    qr_code = CloudinaryField('qr_code', blank=True, null=True)
    
    class Meta:
        db_table = 'siswa'
        
    def __str__(self):
        return f"{self.nama} ({self.nis})"
    @property
    def bisa_edit(self):
        return self.status == 'aktif'

    @property
    def profil_lengkap(self):
        return bool(self.nama and self.kelas and self.jurusan and self.email and self.no_hp)
    
    def save(self, *args, **kwargs):
        if self.tingkat is None or self.tingkat < 10:
            self.tingkat = 10
        super().save(*args, **kwargs)
    
class Tahun_ajaran(models.Model):
    status_choices = [
        ('aktif','aktif'),
        ('nonaktif','nonaktif')
    ]
    tahun_ajaran = models.CharField(max_length=100)
    status = models.CharField(max_length=100, choices=status_choices, default='aktif')
    
    class Meta:
        db_table = 'tahun_ajaran'
        
    def __str__(self):
        return self.tahun_ajaran
    
class Kesiswaan(models.Model):
    user =models.OneToOneField(Users, on_delete=models.CASCADE, related_name='kesiswaan')
    nama = models.CharField(max_length=100, blank=True, default='')
    nip = models.CharField(max_length=100, unique=True)
    jabatan = models.CharField(max_length=100, null=True, blank=True)
    
    class Meta:
        db_table = 'kesiswaan'
        
    def __str__(self):
        return self.nama

    @property
    def profil_lengkap(self):
        return bool(self.nama and self.jabatan)
    
class Prestasi(models.Model):
    siswa = models.ForeignKey(Siswa, on_delete=models.CASCADE)
    tahun_ajaran = models.ForeignKey(Tahun_ajaran, on_delete=models.CASCADE)
    kesiswaan = models.ForeignKey(Kesiswaan, on_delete=models.SET_NULL, null=True, blank=True)
    nama_prestasi = models.CharField(max_length=100)
    tanggal_prestasi = models.DateField()
    penyelenggara = models.CharField(max_length=100)
    tingkat_prestasi = models.CharField(max_length=100,)
    deskripsi = models.TextField()
    status = models.CharField(max_length=100, choices=[
        ('pending','pending'),
        ('diterima','diterima'),
        ('perbaikan','perbaikan'),
        ('ditolak','ditolak'),
    ], default='pending')
    alasan_penolakan = models.TextField(null=True, blank=True)

    # Perbaikan -- kesiswaan bisa kembalikan prestasi ke siswa untuk diperbaiki
    # tanpa langsung menolaknya. jenis_perbaikan cuma keisi kalau status == 'perbaikan'.
    jenis_perbaikan = models.CharField(max_length=10, null=True, blank=True, choices=[
        ('data', 'Perbaikan Data'),
        ('file', 'Perbaikan File'),
    ])
    catatan_perbaikan = models.TextField(null=True, blank=True)
    kategori_prestasi = models.CharField(max_length=100, choices=[
        ('akademik','akademik'),
        ('non-akademik','non-akademik'),
    ])
    tanggal_upload = models.DateTimeField(auto_now_add=True)
    tanggal_verifikasi = models.DateTimeField(null=True, blank=True)

    # Dokumen Puspresnas -- OPSIONAL, cuma relevan kalau tingkat_prestasi == 'nasional'.
    # Puspresnas (Pusat Prestasi Nasional, Kemendikbud) punya sistem klasifikasi
    # sendiri buat prestasi tingkat nasional: berdasarkan wilayah penyelenggaraan
    # dan jenis penyelenggara.
    dokumen_puspresnas = CloudinaryField('dokumen_puspresnas', resource_type='auto', blank=True, null=True)
    jenis_wilayah_puspresnas = models.CharField(max_length=50, blank=True, null=True, choices=[
        ('dalam_negeri', 'Dalam Negeri'),
        ('luar_negeri', 'Luar Negeri'),
    ])
    jenis_penyelenggara_puspresnas = models.CharField(max_length=50, blank=True, null=True, choices=[
        ('kementerian', 'Kementerian'),
        ('non_kementerian', 'Non-Kementerian (Swasta)'),
    ])

    class Meta:
        db_table = 'prestasi'
        
    def __str__(self):
        return self.nama_prestasi
    
class LogAktivitas(models.Model):
    """
    Catatan jejak aktivitas administratif (dibuat/dihapusnya akun, dsb),
    dipakai untuk menampilkan Activity Log di dashboard admin.
    """
    AKSI_CHOICES = [
        ('akun_dibuat', 'Akun dibuat'),
        ('akun_dihapus', 'Akun dihapus'),
    ]
    aksi = models.CharField(max_length=50, choices=AKSI_CHOICES)
    judul = models.CharField(max_length=150)
    deskripsi = models.TextField(blank=True, default='')
    actor = models.CharField(max_length=100, blank=True, default='')
    waktu = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'log_aktivitas'
        ordering = ['-waktu']

    def __str__(self):
        return self.judul


class Sertifikat(models.Model):
    prestasi = models.ForeignKey(Prestasi, on_delete=models.CASCADE)
    file = CloudinaryField('file', resource_type='auto')
    deskripsi = models.TextField()
    
    class Meta:
        db_table = 'sertifikat'
        
    def __str__(self):
        return f'sertifikat #{self.pk} - {self.prestasi.nama_prestasi}'
    
class Dokumentasi(models.Model):
    prestasi = models.ForeignKey(Prestasi, on_delete=models.CASCADE)
    foto = CloudinaryField('foto')
    caption = models.CharField(max_length=100, null=True, blank=True)
    tanggal_dibuat = models.DateTimeField(auto_now_add=True)
    
    class Meta :
        db_table = 'dokumentasi'
        
    def __str__(self):
        return self.caption or f'dokumentasi #{self.pk}'