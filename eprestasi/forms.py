from django import forms
from .models import Siswa, Kesiswaan, Users, Prestasi, Sertifikat, Dokumentasi


class SiswaAkunForm(forms.Form):
    """
    Form akun siswa untuk admin.
    - Mode tambah : hanya NIS + password. Username akun dibuat otomatis dari NIS.
      Data lain (nama, kelas, jurusan, dst) akan diisi siswa sendiri setelah login pertama.
    - Mode edit   : admin hanya boleh memperbaiki NIS, reset password, koreksi tingkat,
      dan mengubah status (aktif/alumni) secara manual bila diperlukan.
    """
    nis = forms.CharField(
        max_length=100,
        label='NIS',
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nomor Induk Siswa'})
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Password awal'}),
        required=False,
        help_text='Kosongkan jika tidak ingin mengubah password.'
    )
    tingkat = forms.IntegerField(
        min_value=10, max_value=12,
        required=False,
        widget=forms.NumberInput(attrs={'class': 'form-control'})
    )
    status = forms.ChoiceField(
        choices=[('aktif', 'Aktif'), ('alumni', 'Alumni')],
        widget=forms.Select(attrs={'class': 'form-select'}),
        required=False,
    )

    def __init__(self, *args, siswa_id=None, **kwargs):
        self.siswa_id = siswa_id
        super().__init__(*args, **kwargs)
        if siswa_id is None:
            # Mode tambah: hanya NIS + password yang relevan
            self.fields['password'].required = True
            del self.fields['tingkat']
            del self.fields['status']

    def clean_nis(self):
        nis = self.cleaned_data['nis']
        qs = Siswa.objects.filter(nis=nis)
        if self.siswa_id:
            qs = qs.exclude(id=self.siswa_id)
        if qs.exists():
            raise forms.ValidationError('NIS sudah terdaftar!')
        return nis


class KesiswaanAkunForm(forms.Form):
    """
    Form akun kesiswaan untuk admin.
    - Mode tambah : hanya NIP + password. Username akun dibuat otomatis dari NIP.
      Nama & jabatan diisi user kesiswaan sendiri setelah login pertama.
    - Mode edit   : admin hanya boleh memperbaiki NIP dan reset password.
    """
    nip = forms.CharField(
        max_length=100,
        label='NIP',
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nomor Induk Pegawai'})
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Password awal'}),
        required=False,
        help_text='Kosongkan jika tidak ingin mengubah password.'
    )

    def __init__(self, *args, kesiswaan_id=None, **kwargs):
        self.kesiswaan_id = kesiswaan_id
        super().__init__(*args, **kwargs)
        if kesiswaan_id is None:
            self.fields['password'].required = True

    def clean_nip(self):
        nip = self.cleaned_data['nip']
        qs = Kesiswaan.objects.filter(nip=nip)
        if self.kesiswaan_id:
            qs = qs.exclude(id=self.kesiswaan_id)
        if qs.exists():
            raise forms.ValidationError('NIP sudah terdaftar!')
        return nip


class TahunAjaranForm(forms.Form):
    tahun_ajaran = forms.CharField(
        max_length=100,
        label='Tahun Ajaran',
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Contoh: 2025/2026'})
    )
    status = forms.ChoiceField(
        choices=[('aktif', 'Aktif'), ('nonaktif', 'Nonaktif')],
        widget=forms.Select(attrs={'class': 'form-select'})
    )


class AdminAkunForm(forms.Form):
    """
    Form kelola akun admin, hanya bisa diakses super_admin.
    CATATAN: form ini hanya bisa membuat role='admin' (admin biasa).
    Membuat/menaikkan seseorang jadi 'super_admin' sengaja TIDAK disediakan lewat web
    sama sekali -- itu cuma bisa lewat command `python manage.py buat_admin --super`
    di terminal, supaya hak akses tertinggi tidak bisa dibuat lewat form manapun.
    """
    username = forms.CharField(
        max_length=100,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Username login admin'})
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Password'}),
        required=False,
        help_text='Kosongkan jika tidak ingin mengubah password.'
    )

    def __init__(self, *args, admin_id=None, **kwargs):
        self.admin_id = admin_id
        super().__init__(*args, **kwargs)
        if admin_id is None:
            self.fields['password'].required = True

    def clean_username(self):
        username = self.cleaned_data['username']
        qs = Users.objects.filter(username=username)
        if self.admin_id:
            qs = qs.exclude(id=self.admin_id)
        if qs.exists():
            raise forms.ValidationError('Username telah digunakan!')
        return username


class SiswaProfilForm(forms.Form):
    """
    Form yang diisi SISWA SENDIRI (bukan admin) untuk melengkapi profilnya
    setelah login pertama kali. nama, kelas, jurusan WAJIB diisi (itu yang
    menentukan Siswa.profil_lengkap). email & no_hp opsional.
    """
    nama = forms.CharField(
        max_length=100,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nama lengkap kamu'})
    )
    kelas = forms.CharField(
        max_length=100,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Contoh: XI RPL 2'})
    )
    jurusan = forms.ChoiceField(
        choices=[
            ('RPL', 'RPL'), ('TKJ', 'TKJ'), ('MPLB', 'MPLB'), ('PM', 'PM'), ('AKL', 'AKL'),
        ],
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    email = forms.EmailField(
        required=False,
        widget=forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'Opsional'})
    )
    no_hp = forms.CharField(
        max_length=100, required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Opsional, contoh: 08123456789'})
    )


TINGKAT_PRESTASI_CHOICES = [
    ('sekolah', 'Sekolah'),
    ('kabupaten/kota', 'Kabupaten/Kota'),
    ('provinsi', 'Provinsi'),
    ('nasional', 'Nasional'),
    ('internasional', 'Internasional'),
]


class PrestasiUploadForm(forms.Form):
    """
    Form upload prestasi BARU oleh siswa. Sekaligus wajib melampirkan
    minimal 1 file sertifikat (bukti), karena tanpa bukti prestasinya
    tidak ada gunanya untuk diverifikasi kesiswaan.
    """
    nama_prestasi = forms.CharField(
        max_length=100,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Contoh: Juara 1 LKS Web Design'})
    )
    kategori_prestasi = forms.ChoiceField(
        choices=[('akademik', 'Akademik'), ('non-akademik', 'Non-Akademik'), ('kejuaraan', 'Kejuaraan')],
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    tingkat_prestasi = forms.ChoiceField(
        choices=TINGKAT_PRESTASI_CHOICES,
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    penyelenggara = forms.CharField(
        max_length=100,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Contoh: Dinas Pendidikan Provinsi'})
    )
    tanggal_prestasi = forms.DateField(
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'})
    )
    deskripsi = forms.CharField(
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 4, 'placeholder': 'Ceritakan sedikit tentang prestasi ini'})
    )

    # Wajib lampirkan minimal 1 bukti sertifikat sekaligus di form yang sama
    file_sertifikat = forms.FileField(
        label='File Sertifikat (bukti)',
        widget=forms.ClearableFileInput(attrs={'class': 'form-control'})
    )
    deskripsi_sertifikat = forms.CharField(
        max_length=255, required=False,
        label='Keterangan file (opsional)',
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Contoh: Sertifikat asli, halaman depan'})
    )


class SertifikatTambahanForm(forms.Form):
    """Dipakai buat nambah bukti sertifikat SUSULAN ke prestasi yang sudah ada."""
    file = forms.FileField(
        label='File Sertifikat',
        widget=forms.ClearableFileInput(attrs={'class': 'form-control'})
    )
    deskripsi = forms.CharField(
        max_length=255, required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Opsional'})
    )


class DokumentasiTambahanForm(forms.Form):
    """Dipakai buat nambah foto dokumentasi (bukan sertifikat resmi, tapi foto kegiatan/lomba)."""
    foto = forms.ImageField(
        widget=forms.ClearableFileInput(attrs={'class': 'form-control'})
    )
    caption = forms.CharField(
        max_length=100, required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Opsional'})
    )


class KesiswaanProfilForm(forms.Form):
    """
    Form yang diisi user KESISWAAN SENDIRI (bukan admin) setelah login pertama kali.
    Sama seperti siswa: admin cuma bikin akun dgn NIP+password, nama & jabatan
    diisi sendiri -- itu yang menentukan Kesiswaan.profil_lengkap.
    """
    nama = forms.CharField(
        max_length=100,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nama lengkap kamu'})
    )
    jabatan = forms.CharField(
        max_length=100,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Contoh: Wakil Kesiswaan'})
    )


class VerifikasiPrestasiForm(forms.Form):
    """
    Form keputusan verifikasi oleh kesiswaan. alasan_penolakan WAJIB diisi
    kalau keputusannya 'ditolak' (dicek manual di clean(), bukan lewat required=True,
    karena wajib/tidaknya tergantung pilihan keputusan).
    """
    keputusan = forms.ChoiceField(
        choices=[('diterima', 'Terima'), ('ditolak', 'Tolak')],
        widget=forms.RadioSelect
    )
    alasan_penolakan = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Wajib diisi kalau prestasi ditolak'})
    )

    def clean(self):
        cleaned_data = super().clean()
        keputusan = cleaned_data.get('keputusan')
        alasan = cleaned_data.get('alasan_penolakan', '').strip()

        if keputusan == 'ditolak' and not alasan:
            self.add_error('alasan_penolakan', 'Alasan penolakan wajib diisi kalau prestasi ditolak.')

        return cleaned_data
