from django.db import models
from django.utils import timezone
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
    status = models.CharField(max_length=100, choices=[
        ('aktif', 'aktif'),
        ('nonaktif', 'nonaktif'),
        ('alumni', 'alumni'),
    ], default='aktif')
    nama = models.CharField(max_length=100, blank=True, default='')
    # Kelas saat ini (disinkronkan dari RiwayatKelas tahun ajaran aktif). Sengaja tanpa
    # choices: daftar kelas dibuat admin per tahun ajaran di model Kelas.
    kelas = models.CharField(max_length=100, blank=True, null=True)
    JURUSAN_CHOICES = [
        ('RPL', 'RPL'),
        ('DKV', 'DKV'),
        ('TKJ', 'TKJ'),
        ('AKL', 'AKL'),
        ('MPLB', 'MPLB'),
        ('PM', 'PM'),
    ]
    jurusan = models.CharField(max_length=100, blank=True, null=True, choices = JURUSAN_CHOICES)
    email = models.EmailField(max_length=100, blank=True, null=True)
    no_hp = models.CharField(max_length=100, blank=True, null=True)
    alamat = models.TextField(blank=True, default='')
    foto_profil = CloudinaryField('foto_profil', blank=True, null=True)
    qr_code = CloudinaryField('qr_code', blank=True, null=True)

    # ── Kelulusan ────────────────────────────────────────────────────────
    # Status kelulusan TERPISAH dari status siswa (aktif/nonaktif/alumni).
    # Siswa tingkat XII berstatus 'belum_diproses' sampai admin menjalankan
    # aksi "Proses Kelulusan" di halaman Kelulusan & Alumni. Setelah
    # diluluskan, status siswa ikut berubah menjadi 'alumni' (data historis
    # & relasi prestasi tetap dipertahankan, tidak dihapus).
    STATUS_KELULUSAN_CHOICES = [
        ('belum_diproses', 'Belum Diproses'),
        ('lulus', 'Lulus'),
        ('tidak_lulus', 'Tidak Lulus'),
    ]
    status_kelulusan = models.CharField(
        max_length=20, choices=STATUS_KELULUSAN_CHOICES, default='belum_diproses'
    )
    tanggal_kelulusan = models.DateField(null=True, blank=True)

    class Meta:
        db_table = 'siswa'
        
    def __str__(self):
        return f"{self.nama} ({self.nis})"
    @property
    def bisa_edit(self):
        return self.status == 'aktif'

    @property
    def profil_lengkap(self):
        return bool(self.nama and self.kelas and self.jurusan and self.email and self.no_hp and self.alamat)
    
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
    # Nilai disimpan sama dengan labelnya supaya data lama ("Wakil Kesiswaan")
    # tetap valid tanpa perlu migrasi data.
    JABATAN_CHOICES = [
        ('Wakil Kesiswaan', 'Wakil Kesiswaan'),
        ('Ketua Kesiswaan', 'Ketua Kesiswaan'),
    ]
    jabatan = models.CharField(max_length=100, null=True, blank=True, choices=JABATAN_CHOICES)
    no_hp = models.CharField(max_length=20, blank=True, default='')
    status = models.CharField(max_length=20, choices=[
        ('aktif', 'aktif'),
        ('nonaktif', 'nonaktif'),
    ], default='aktif')
    
    class Meta:
        db_table = 'kesiswaan'
        
    def __str__(self):
        return self.nama

    @property
    def profil_lengkap(self):
        return bool(self.nama and self.no_hp and self.jabatan)
    
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
        ('kejuaraan','kejuaraan'),
    ])
    tanggal_upload = models.DateTimeField(auto_now_add=True)
    tanggal_verifikasi = models.DateTimeField(null=True, blank=True)

    # Lokasi/wilayah penyelenggaraan prestasi: dalam negeri atau luar negeri.
    # Berlaku untuk SEMUA prestasi (wajib diisi di form upload).
    wilayah_prestasi = models.CharField(max_length=20, default='dalam_negeri', choices=[
        ('dalam_negeri', 'Dalam Negeri'),
        ('luar_negeri', 'Luar Negeri'),
    ])

    # Kode & Dokumen Puspresnas -- OPSIONAL, bisa diisi di semua tingkat prestasi.
    # Puspresnas (Pusat Prestasi Nasional, Kemendikbud) punya sistem klasifikasi
    # berdasarkan wilayah penyelenggaraan dan jenis penyelenggara.
    kode_puspresnas = models.CharField(max_length=100, blank=True, null=True)
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

    @property
    def tampilkan_tag_puspresnas(self):
        """Dipakai template untuk badge PUSPRESNAS: true kalau ada kode atau dokumen."""
        return bool(self.kode_puspresnas or self.dokumen_puspresnas)
    
class LogAktivitas(models.Model):
    """
    Catatan jejak aktivitas administratif dalam sistem (tambah/ubah/hapus data,
    verifikasi prestasi, import, dsb), dipakai untuk halaman Log Aktivitas dan
    widget "Aktivitas Terbaru" di Dashboard Admin.
    """
    AKSI_CHOICES = [
        ('akun_dibuat', 'Akun dibuat'),
        ('akun_diubah', 'Akun diubah'),
        ('akun_dihapus', 'Akun dihapus'),
        ('status_diubah', 'Status diubah'),
        ('user_diimport', 'User diimport'),
        ('tahun_ajaran_ditambah', 'Tahun ajaran ditambah'),
        ('tahun_ajaran_diubah', 'Tahun ajaran diubah'),
        ('prestasi_diverifikasi', 'Prestasi diverifikasi'),
        ('kelas_dibuat', 'Kelas dibuat'),
        ('kelas_dihapus', 'Kelas dihapus'),
        ('siswa_ditempatkan_kelas', 'Siswa ditempatkan ke kelas'),
        ('kelulusan_diproses', 'Kelulusan diproses'),
        ('password_direset', 'Password direset'),
    ]
    MODUL_CHOICES = [
        ('siswa', 'Siswa'),
        ('kesiswaan', 'Kesiswaan'),
        ('admin', 'Admin'),
        ('tahun_ajaran', 'Tahun Ajaran'),
        ('kelas', 'Kelas'),
        ('prestasi', 'Prestasi'),
        ('kelulusan', 'Kelulusan'),
        ('import', 'Import'),
    ]
    STATUS_LOG_CHOICES = [
        ('berhasil', 'Berhasil'),
        ('gagal', 'Gagal'),
    ]
    aksi = models.CharField(max_length=50, choices=AKSI_CHOICES)
    judul = models.CharField(max_length=150)
    deskripsi = models.TextField(blank=True, default='')
    actor = models.CharField(max_length=100, blank=True, default='')
    role_actor = models.CharField(max_length=50, blank=True, default='')
    modul = models.CharField(max_length=20, choices=MODUL_CHOICES, blank=True, default='')
    status_log = models.CharField(max_length=20, choices=STATUS_LOG_CHOICES, default='berhasil')
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


# =========================================================
# PENGELOLAAN KELAS & RIWAYAT KELAS SISWA
# =========================================================
# Prinsip utama fitur ini:
# 1. Jurusan siswa (Siswa.jurusan) bersifat TETAP selama siswa bersekolah.
# 2. Kelas siswa TIDAK disimpan cukup sebagai satu nilai di data siswa,
#    karena kelas berubah setiap tahun ajaran. Kondisi kelas siswa pada
#    setiap tahun ajaran disimpan di tabel RiwayatKelas, dan setiap
#    kejadian penempatan/perubahan kelas dicatat permanen di
#    LogPerubahanKelas (append-only, tidak pernah diubah/dihapus).
# Field Siswa.kelas/Siswa.tingkat yang lama tetap dipertahankan (dipakai
# fitur-fitur lain seperti daftar siswa & portofolio publik) dan akan
# disinkronkan otomatis setiap kali RiwayatKelas siswa diperbarui, supaya
# fitur yang sudah berjalan tidak rusak.

DAFTAR_JURUSAN = [
    ('RPL', 'RPL'),
    ('TKJ', 'TKJ'),
    ('DKV', 'DKV'),
    ('MPLB', 'MPLB'),
    ('AKL', 'AKL'),
    ('PM', 'PM'),
]

DAFTAR_TINGKAT = [
    (10, 'X'),
    (11, 'XI'),
    (12, 'XII'),
]

TINGKAT_KE_ROMAWI = {10: 'X', 11: 'XI', 12: 'XII'}
ROMAWI_KE_TINGKAT = {'X': 10, 'XI': 11, 'XII': 12}


class Kelas(models.Model):
    """
    Daftar kelas berdasarkan jurusan & tingkat, dibuat PER TAHUN AJARAN.
    Contoh: "XI RPL 2" pada tahun ajaran 2025/2026 adalah baris yang berbeda
    dari "XI RPL 2" pada tahun ajaran 2026/2027 -- supaya kondisi kelas pada
    suatu tahun ajaran tertentu tetap bisa dilihat kembali kapan saja tanpa
    tertimpa oleh perubahan di tahun ajaran berikutnya.
    """
    nama_kelas = models.CharField(max_length=100)
    jurusan = models.CharField(max_length=10, choices=DAFTAR_JURUSAN)
    tingkat = models.PositiveSmallIntegerField(choices=DAFTAR_TINGKAT)
    tahun_ajaran = models.ForeignKey(
        Tahun_ajaran, on_delete=models.CASCADE, related_name='daftar_kelas'
    )
    dibuat_pada = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'kelas'
        unique_together = ('nama_kelas', 'tahun_ajaran')
        ordering = ['tahun_ajaran_id', 'jurusan', 'tingkat', 'nama_kelas']

    def __str__(self):
        return f"{self.nama_kelas} ({self.tahun_ajaran.tahun_ajaran})"

    @property
    def tingkat_romawi(self):
        return TINGKAT_KE_ROMAWI.get(self.tingkat, '')

    @property
    def jumlah_siswa(self):
        return self.riwayat_kelas.count()


class RiwayatKelas(models.Model):
    """
    Kondisi kelas siswa PADA SATU TAHUN AJARAN. Satu siswa hanya boleh
    mempunyai SATU baris untuk satu tahun ajaran yang sama
    (unique_together siswa + tahun_ajaran) -- ini yang mencegah penempatan
    ganda siswa pada tahun ajaran yang sama (Aturan #18).

    Baris milik tahun ajaran yang SUDAH LEWAT tidak pernah diubah atau
    ditimpa (Aturan #10) -- begitu tahun ajaran baru dibuat & siswa
    ditempatkan ke kelas baru, baris tahun ajaran lama otomatis "terkunci"
    karena penempatan berikutnya selalu masuk ke baris tahun ajaran yang
    baru, bukan menimpa baris lama.

    Baris milik tahun ajaran yang SEDANG BERJALAN masih boleh diperbarui,
    misalnya saat admin melakukan perubahan manual pembagian kelas XII
    (lihat bagian 8 spesifikasi) -- setiap pembaruan tetap dicatat sebagai
    kejadian baru di LogPerubahanKelas supaya jejaknya tidak hilang.
    """
    siswa = models.ForeignKey(Siswa, on_delete=models.CASCADE, related_name='riwayat_kelas')
    kelas = models.ForeignKey(Kelas, on_delete=models.CASCADE, related_name='riwayat_kelas')
    tahun_ajaran = models.ForeignKey(
        Tahun_ajaran, on_delete=models.CASCADE, related_name='riwayat_kelas'
    )
    tingkat = models.PositiveSmallIntegerField(choices=DAFTAR_TINGKAT)
    tanggal_penempatan = models.DateTimeField(default=timezone.now)
    diubah_oleh = models.ForeignKey(
        Users, on_delete=models.SET_NULL, null=True, blank=True, related_name='+'
    )

    class Meta:
        db_table = 'riwayat_kelas'
        unique_together = ('siswa', 'tahun_ajaran')
        ordering = ['tahun_ajaran_id', 'siswa_id']

    def __str__(self):
        return f"{self.siswa.nama} - {self.kelas.nama_kelas} ({self.tahun_ajaran.tahun_ajaran})"


class LogPerubahanKelas(models.Model):
    """
    Jejak audit APPEND-ONLY setiap kali kelas siswa ditempatkan atau diubah.
    Berbeda dengan RiwayatKelas (yang baris tahun-ajaran-aktifnya boleh
    diperbarui), tabel ini tidak pernah diedit maupun dihapus, sehingga
    seluruh riwayat perubahan kelas siswa -- termasuk siapa yang mengubah,
    kapan, dan alasannya -- tetap bisa ditelusuri (Aturan #14, bagian 12).
    """
    JENIS_PERUBAHAN_CHOICES = [
        ('penempatan_awal', 'Penempatan awal'),
        ('pembagian_ulang_x_ke_xi', 'Pembagian ulang kelas X ke XI'),
        ('kenaikan_otomatis_xi_ke_xii', 'Kenaikan otomatis XI ke XII'),
        ('perubahan_manual', 'Perubahan manual'),
    ]
    siswa = models.ForeignKey(Siswa, on_delete=models.CASCADE, related_name='log_perubahan_kelas')
    kelas_sebelumnya = models.ForeignKey(
        Kelas, on_delete=models.SET_NULL, null=True, blank=True, related_name='+'
    )
    kelas_baru = models.ForeignKey(
        Kelas, on_delete=models.SET_NULL, null=True, blank=True, related_name='+'
    )
    tahun_ajaran = models.ForeignKey(
        Tahun_ajaran, on_delete=models.CASCADE, related_name='log_perubahan_kelas'
    )
    jenis_perubahan = models.CharField(max_length=30, choices=JENIS_PERUBAHAN_CHOICES)
    alasan_perubahan = models.TextField(null=True, blank=True)
    diubah_oleh = models.ForeignKey(
        Users, on_delete=models.SET_NULL, null=True, blank=True, related_name='+'
    )
    waktu_perubahan = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'log_perubahan_kelas'
        ordering = ['-waktu_perubahan']

    def __str__(self):
        sebelumnya = self.kelas_sebelumnya.nama_kelas if self.kelas_sebelumnya else '-'
        baru = self.kelas_baru.nama_kelas if self.kelas_baru else '-'
        return f"{self.siswa.nama}: {sebelumnya} -> {baru}"
    
class NotifikasiDibaca(models.Model):
    """Penanda bahwa seorang kesiswaan sudah membuka notifikasi pengajuan tertentu."""
    kesiswaan = models.ForeignKey(Kesiswaan, on_delete=models.CASCADE, related_name='notifikasi_dibaca')
    prestasi = models.ForeignKey(Prestasi, on_delete=models.CASCADE, related_name='notifikasi_dibaca')
    dibaca_pada = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = 'notifikasi_dibaca'
        unique_together = ('kesiswaan', 'prestasi')

class NotifikasiSiswa(models.Model):
    """Pemberitahuan hasil verifikasi untuk siswa. Satu baris per keputusan."""
    siswa = models.ForeignKey(Siswa, on_delete=models.CASCADE, related_name='notifikasi')
    prestasi = models.ForeignKey(Prestasi, on_delete=models.CASCADE, related_name='notifikasi_siswa')
    status = models.CharField(max_length=20)          # diterima / perbaikan / ditolak
    pesan = models.CharField(max_length=255)
    dibuat_pada = models.DateTimeField(auto_now_add=True)
    dibaca = models.BooleanField(default=False)

    class Meta:
        db_table = 'notifikasi_siswa'
        ordering = ['-dibuat_pada']


class LoginAttempt(models.Model):
    """
    Pencatat percobaan login gagal untuk pembatasan (rate limit) di halaman login.
    `kunci` adalah hash dari username/NIS/NIP yang diketik, jadi tidak
    menyimpan data mentah dan tidak membocorkan apakah akun tersebut ada.
    """
    kunci = models.CharField(max_length=64, unique=True)
    jumlah_gagal = models.PositiveIntegerField(default=0)
    terakhir_gagal = models.DateTimeField(default=timezone.now)
    terkunci_sampai = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'login_attempt'