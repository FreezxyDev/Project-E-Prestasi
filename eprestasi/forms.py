from django import forms
from django.core.exceptions import ValidationError
from .models import Siswa, Kesiswaan, Users, Prestasi, Sertifikat, Dokumentasi


# ── Pemetaan Kelas berdasarkan Jurusan ──────────────────────────────────────
# Dipakai supaya dropdown "Kelas" di form Tambah/Edit Siswa cuma menampilkan
# kelas yang relevan dengan Jurusan yang dipilih admin (filter di JS, lihat
# templates/eprestasi/siswa/form.html), dan divalidasi ulang di server lewat
# SiswaAkunForm.clean() di bawah.
KELAS_PER_JURUSAN = {
    'RPL': ['X PPLG 1', 'X PPLG 2', 'XI RPL 1', 'XI RPL 2', 'XII RPL 1', 'XII RPL 2'],
    'DKV': ['X DKV 1', 'X DKV 2', 'XI DKV 1', 'XI DKV 2', 'XII DKV 1', 'XII DKV 2'],
    'TJKT': ['X TJKT 1', 'XI TJKT 1', 'XII TJKT 1'],
    'PM': [
        'X PM 1', 'X PM 2', 'X PM 3',
        'XI PM 1', 'XI PM 2', 'XI PM 3',
        'XII PM 1', 'XII PM 2', 'XII PM 3',
    ],
    'MPLB': [
        'X MP 1', 'X MP 2', 'X MP 3', 'X MP 4', 'X MP 5',
        'XI MP 1', 'XI MP 2', 'XI MP 3', 'XI MP 4', 'XI MP 5',
        'XII MP 1', 'XII MP 2', 'XII MP 3', 'XII MP 4', 'XII MP 5',
    ],
    'AKL': [
        'X AKL 1', 'X AKL 2', 'X AKL 3', 'X AKL 4',
        'XI AKL 1', 'XI AKL 2', 'XI AKL 3', 'XI AKL 4',
        'XII AKL 1', 'XII AKL 2', 'XII AKL 3', 'XII AKL 4',
    ],
}

# Reverse map: nama kelas -> jurusan. Dipakai buat kasih atribut data-jurusan
# ke tiap <option> Kelas (lihat KelasSelectWidget di bawah).
_JURUSAN_PER_KELAS = {
    kelas: jurusan
    for jurusan, daftar_kelas in KELAS_PER_JURUSAN.items()
    for kelas in daftar_kelas
}


class KelasSelectWidget(forms.Select):
    """
    Select HTML biasa, tapi tiap <option> dikasih atribut data-jurusan="RPL"
    dst, supaya JavaScript di form Tambah/Edit Siswa bisa menyembunyikan opsi
    kelas yang tidak sesuai dengan Jurusan yang lagi dipilih.
    """
    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex, attrs)
        jurusan = _JURUSAN_PER_KELAS.get(value)
        if jurusan:
            option['attrs']['data-jurusan'] = jurusan
        return option


MAKS_UKURAN_FILE_MB = 5
MAKS_UKURAN_FILE_BYTES = MAKS_UKURAN_FILE_MB * 1024 * 1024


def validasi_ukuran_file(file):
    """
    Validator custom -- Django tidak punya validasi ukuran file bawaan.
    Dipakai di semua field upload (sertifikat & dokumentasi) supaya siswa
    tidak bisa upload file lebih dari 5MB (Cloudinary free tier juga ada
    batas kuota, jadi ini sekalian jaga-jaga).
    """
    if file.size > MAKS_UKURAN_FILE_BYTES:
        ukuran_mb = file.size / (1024 * 1024)
        raise ValidationError(
            f'Ukuran file maksimal {MAKS_UKURAN_FILE_MB}MB. File kamu {ukuran_mb:.1f}MB.'
        )


from django import forms
from .models import Siswa

class SiswaAkunForm(forms.Form):
    nis = forms.CharField(
        max_length=20,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Masukkan NIS'})
    )
    nama = forms.CharField(
        max_length=100,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Masukkan Nama Lengkap'})
    )
    kelas = forms.ChoiceField(
        choices=[('', '-- Pilih Jurusan dulu --')] + list(Siswa.KELAS_CHOICES),
        widget=KelasSelectWidget(attrs={'class': 'form-select'})
    )
    jurusan = forms.ChoiceField(
        choices=[('', '-- Pilih Jurusan --')] + list(Siswa.JURUSAN_CHOICES),
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    tingkat = forms.IntegerField(
        required=False,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'min': 10, 'placeholder': 'Contoh: 10, 11, 12', 'value': 10})
    )
    status = forms.ChoiceField(
        choices=[('aktif', 'Aktif'), ('alumni', 'Alumni')],
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    password = forms.CharField(
        required=False,  # default False; jadi wajib khusus mode tambah (lihat __init__)
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Masukkan Password'})
    )

    def __init__(self, *args, **kwargs):
        self.siswa_id = kwargs.pop('siswa_id', None)
        super().__init__(*args, **kwargs)
        if self.siswa_id is None:
            # Mode tambah akun baru -> password wajib diisi.
            self.fields['password'].required = True
        else:
            # Mode edit -> password opsional, cuma diganti kalau diisi.
            self.fields['password'].help_text = 'Kosongkan jika tidak ingin mengubah password.'

    def clean_nis(self):
        nis = self.cleaned_data.get('nis')
        # Cek keunikan NIS (kecuali milik diri sendiri saat edit)
        qs = Siswa.objects.filter(nis=nis)
        if self.siswa_id:
            qs = qs.exclude(id=self.siswa_id)
        if qs.exists():
            raise forms.ValidationError('NIS sudah terdaftar.')
        return nis

    def clean(self):
        cleaned_data = super().clean()
        jurusan = cleaned_data.get('jurusan')
        kelas = cleaned_data.get('kelas')

        # Validasi ulang di server, jaga-jaga kalau filter JS di browser
        # di-nonaktifkan atau di-bypass -- kelas yang dipilih harus benar-benar
        # milik jurusan yang dipilih.
        if jurusan and kelas and kelas not in KELAS_PER_JURUSAN.get(jurusan, []):
            self.add_error('kelas', 'Kelas yang dipilih tidak sesuai dengan Jurusan.')

        return cleaned_data

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
    setelah login pertama kali. Nama, kelas, dan jurusan SEPENUHNYA diisi
    admin saat akun dibuat -- makanya field itu SENGAJA TIDAK ADA di form ini
    (cuma ditampilkan sebagai teks biasa di template dari data `siswa`
    langsung, lihat siswa_portal/lengkapi_profil.html).

    PENTING: jangan tambahkan field nama/kelas/jurusan ke sini lagi. Kalau
    ditambah sebagai field wajib tapi template tidak merender inputnya,
    form ini akan SELALU gagal validasi (karena field itu tidak pernah ada
    di request.POST) -- inilah yang dulu menyebabkan siswa terjebak
    redirect loop terus-menerus ke halaman "Lengkapi Profil".
    """
    email = forms.EmailField(
        widget=forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'contoh@email.com'})
    )
    no_hp = forms.CharField(
        max_length=100,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Contoh: 08123456789'})
    )


TINGKAT_PRESTASI_CHOICES = [
    ('sekolah', 'Sekolah'),
    ('kabupaten/kota', 'Kabupaten/Kota'),
    ('provinsi', 'Provinsi'),
    ('nasional', 'Nasional'),
]


class PrestasiUploadForm(forms.Form):
    """
    Form upload prestasi BARU oleh siswa. Wajib melampirkan 2 bukti sekaligus:
    file sertifikat (bukti prestasi) DAN foto dokumentasi -- keduanya wajib,
    tanpa bukti yang lengkap prestasinya tidak ada gunanya untuk diverifikasi.

    Dokumen Puspresnas OPSIONAL, cuma relevan/ditampilkan kalau tingkat_prestasi
    dipilih 'nasional' -- makanya semua field puspresnas di sini required=False
    di level form, validasinya (saling melengkapi 1 sama lain) dicek manual di
    clean(), bukan lewat required=True biasa.
    """
    nama_prestasi = forms.CharField(
        max_length=100,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Contoh: Juara 1 LKS Web Design'})
    )
    kategori_prestasi = forms.ChoiceField(
        choices=[('akademik', 'Akademik'), ('non-akademik', 'Non-Akademik')],
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    tingkat_prestasi = forms.ChoiceField(
        choices=TINGKAT_PRESTASI_CHOICES,
        widget=forms.Select(attrs={'class': 'form-select', 'id': 'id_tingkat_prestasi'})
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

    # ── Bukti WAJIB, 2-2nya ──
    file_sertifikat = forms.FileField(
        label='Bukti Prestasi (Sertifikat)',
        validators=[validasi_ukuran_file],
        help_text=f'Maksimal {MAKS_UKURAN_FILE_MB}MB.',
        widget=forms.ClearableFileInput(attrs={'class': 'form-control'})
    )
    deskripsi_sertifikat = forms.CharField(
        max_length=255, required=False,
        label='Keterangan bukti prestasi (opsional)',
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Contoh: Sertifikat asli, halaman depan'})
    )
    foto_dokumentasi = forms.ImageField(
        label='Bukti Dokumentasi (Foto)',
        validators=[validasi_ukuran_file],
        help_text=f'Wajib diisi. Maksimal {MAKS_UKURAN_FILE_MB}MB.',
        widget=forms.ClearableFileInput(attrs={'class': 'form-control'})
    )
    caption_dokumentasi = forms.CharField(
        max_length=100, required=False,
        label='Keterangan dokumentasi (opsional)',
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Contoh: Foto saat penyerahan piala'})
    )

    # ── Dokumen Puspresnas, OPSIONAL, cuma relevan untuk tingkat 'nasional' ──
    dokumen_puspresnas = forms.FileField(
        required=False,
        label='Dokumen Puspresnas (opsional)',
        validators=[validasi_ukuran_file],
        help_text=f'Maksimal {MAKS_UKURAN_FILE_MB}MB.',
        widget=forms.ClearableFileInput(attrs={'class': 'form-control'})
    )
    jenis_wilayah_puspresnas = forms.ChoiceField(
        required=False,
        label='Wilayah',
        choices=[('', '-- Pilih --'), ('dalam_negeri', 'Dalam Negeri'), ('luar_negeri', 'Luar Negeri')],
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    jenis_penyelenggara_puspresnas = forms.ChoiceField(
        required=False,
        label='Jenis Penyelenggara',
        choices=[('', '-- Pilih --'), ('kementerian', 'Kementerian'), ('non_kementerian', 'Non-Kementerian (Swasta)')],
        widget=forms.Select(attrs={'class': 'form-select'})
    )

    def clean(self):
        cleaned_data = super().clean()
        dokumen = cleaned_data.get('dokumen_puspresnas')
        wilayah = cleaned_data.get('jenis_wilayah_puspresnas')
        penyelenggara_jenis = cleaned_data.get('jenis_penyelenggara_puspresnas')

        # Kalau siswa upload dokumen puspresnas, wilayah & jenis penyelenggaranya
        # wajib dipilih juga -- tidak ada gunanya ada dokumen tanpa kategorinya.
        if dokumen and not wilayah:
            self.add_error('jenis_wilayah_puspresnas', 'Wajib dipilih kalau melampirkan dokumen Puspresnas.')
        if dokumen and not penyelenggara_jenis:
            self.add_error('jenis_penyelenggara_puspresnas', 'Wajib dipilih kalau melampirkan dokumen Puspresnas.')

        return cleaned_data


class SertifikatTambahanForm(forms.Form):
    """Dipakai buat nambah bukti sertifikat SUSULAN ke prestasi yang sudah ada."""
    file = forms.FileField(
        label='File Sertifikat',
        validators=[validasi_ukuran_file],
        help_text=f'Maksimal {MAKS_UKURAN_FILE_MB}MB.',
        widget=forms.ClearableFileInput(attrs={'class': 'form-control'})
    )
    deskripsi = forms.CharField(
        max_length=255, required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Opsional'})
    )


class DokumentasiTambahanForm(forms.Form):
    """Dipakai buat nambah foto dokumentasi (bukan sertifikat resmi, tapi foto kegiatan/lomba)."""
    foto = forms.ImageField(
        validators=[validasi_ukuran_file],
        help_text=f'Maksimal {MAKS_UKURAN_FILE_MB}MB.',
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
    
    FIELD READONLY (tidak bisa diedit):
    - nama (data sekolah, dikirim dari admin)
    """
    nama = forms.CharField(
        max_length=100,
        widget=forms.TextInput(attrs={
            'class': 'form-control is-readonly',
            'placeholder': 'Nama lengkap kamu',
            'readonly': 'readonly'
        })
    )
    jabatan = forms.CharField(
        max_length=100,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Contoh: Wakil Kesiswaan'})
    )


class VerifikasiPrestasiForm(forms.Form):
    """
    Form keputusan verifikasi oleh kesiswaan. Ada 3 pilihan keputusan:
    - diterima  : prestasi lolos verifikasi, langsung tampil di portofolio publik.
    - perbaikan : dikembalikan ke siswa untuk diperbaiki (data atau file),
                  wajib pilih jenis_perbaikan + isi catatan_perbaikan.
    - ditolak   : ditolak permanen, wajib isi alasan_penolakan.
    """
    keputusan = forms.ChoiceField(
        choices=[('diterima', 'Terima'), ('perbaikan', 'Perbaiki'), ('ditolak', 'Tolak')],
        widget=forms.RadioSelect
    )
    jenis_perbaikan = forms.ChoiceField(
        choices=[('data', 'Perbaikan Data'), ('file', 'Perbaikan File')],
        required=False,
        widget=forms.RadioSelect
    )
    catatan_perbaikan = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Jelaskan apa yang perlu diperbaiki siswa, wajib diisi kalau memilih Perbaiki'})
    )
    alasan_penolakan = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Wajib diisi kalau prestasi ditolak'})
    )

    def clean(self):
        cleaned_data = super().clean()
        keputusan = cleaned_data.get('keputusan')
        alasan = cleaned_data.get('alasan_penolakan', '').strip()
        jenis_perbaikan = cleaned_data.get('jenis_perbaikan')
        catatan = cleaned_data.get('catatan_perbaikan', '').strip()

        if keputusan == 'ditolak' and not alasan:
            self.add_error('alasan_penolakan', 'Alasan penolakan wajib diisi kalau prestasi ditolak.')

        if keputusan == 'perbaikan':
            if not jenis_perbaikan:
                self.add_error('jenis_perbaikan', 'Pilih jenis perbaikan (data atau file).')
            if not catatan:
                self.add_error('catatan_perbaikan', 'Catatan perbaikan wajib diisi supaya siswa tahu apa yang harus diperbaiki.')

        return cleaned_data


class PrestasiEditForm(forms.Form):
    """
    Dipakai siswa untuk memperbaiki DATA prestasi yang dikembalikan kesiswaan
    dengan jenis_perbaikan='data' (tidak termasuk file -- file sertifikat lama
    tetap ada, tidak perlu upload ulang).
    """
    nama_prestasi = forms.CharField(
        max_length=100,
        widget=forms.TextInput(attrs={'class': 'form-control'})
    )
    kategori_prestasi = forms.ChoiceField(
        choices=[('akademik', 'Akademik'), ('non-akademik', 'Non-Akademik')],
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    tingkat_prestasi = forms.ChoiceField(
        choices=TINGKAT_PRESTASI_CHOICES,
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    penyelenggara = forms.CharField(
        max_length=100,
        widget=forms.TextInput(attrs={'class': 'form-control'})
    )
    tanggal_prestasi = forms.DateField(
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'})
    )
    deskripsi = forms.CharField(
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 4})
    )


class ImportSiswaForm(forms.Form):
    """Form upload file Excel (.xlsx) buat bikin banyak akun siswa sekaligus."""
    file_excel = forms.FileField(
        label='File Excel (.xlsx)',
        widget=forms.ClearableFileInput(attrs={'class': 'form-control', 'accept': '.xlsx'})
    )

    def clean_file_excel(self):
        file = self.cleaned_data['file_excel']
        if not file.name.lower().endswith('.xlsx'):
            raise ValidationError('File harus berformat .xlsx (Excel). Gunakan template yang disediakan.')
        if file.size > MAKS_UKURAN_FILE_BYTES:
            raise ValidationError(f'Ukuran file maksimal {MAKS_UKURAN_FILE_MB}MB.')
        return file