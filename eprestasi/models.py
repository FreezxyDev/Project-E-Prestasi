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
    kelas = models.CharField(max_length=100, blank=True, default='')
    jurusan = models.CharField(max_length=100, blank=True, default='', choices =[
        ('RPL','RPL'),
        ('TKJ','TKJ'),
        ('MPLB','MPLB'),
        ('PM','PM'),
        ('AKL','AKL'),
    ])
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
        return bool(self.nama and self.kelas and self.jurusan)
    
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
        ('ditolak','ditolak'),
    ], default='pending')
    alasan_penolakan = models.TextField(null=True, blank=True)
    kategori_prestasi = models.CharField(max_length=100, choices=[
        ('akademik','akademik'),
        ('non-akademik','non-akademik'),
        ('kejuaraan','kejuaraan'),
    ])
    
    class Meta:
        db_table = 'prestasi'
        
    def __str__(self):
        return self.nama_prestasi
    
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