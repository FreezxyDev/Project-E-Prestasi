from django import forms
from django.core.exceptions import ValidationError
from .models import (
    Siswa, Kesiswaan, Users, Prestasi, Sertifikat, Dokumentasi,
    Kelas, Tahun_ajaran, DAFTAR_JURUSAN, DAFTAR_TINGKAT,
)


class KelasSelectWidget(forms.Select):
    """
    Select biasa, tapi tiap <option> dikasih atribut data-jurusan="RPL" dst
    (diambil dari objek Kelas-nya), supaya JavaScript di form Tambah/Edit
    Siswa bisa menyembunyikan kelas yang tidak sesuai Jurusan yang dipilih.
    """
    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex, attrs)
        instance = getattr(value, 'instance', None)
        if instance is not None:
            option['attrs']['data-jurusan'] = instance.jurusan
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
    """
    Form akun siswa untuk admin. Pilihan Kelas diambil dari model Kelas pada
    TAHUN AJARAN AKTIF (struktur kelas dikelola admin per tahun ajaran di
    Pengelolaan Kelas), bukan daftar tetap. Tingkat ditentukan otomatis dari
    kelas yang dipilih, jadi tidak ada input tingkat di sini.
    """
    nis = forms.CharField(
        max_length=20,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Masukkan NIS'})
    )
    nama = forms.CharField(
        max_length=100,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Masukkan Nama Lengkap'})
    )
    kelas = forms.ModelChoiceField(
        queryset=Kelas.objects.none(),
        empty_label='-- Pilih Jurusan dulu --',
        widget=KelasSelectWidget(attrs={'class': 'form-select'})
    )
    jurusan = forms.ChoiceField(
        choices=[('', '-- Pilih Jurusan --')] + list(Siswa.JURUSAN_CHOICES),
        widget=forms.Select(attrs={'class': 'form-select'})
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
        # Siswa alumni tidak ditempatkan di kelas tahun aktif, jadi kelas tidak wajib.
        kelas_wajib = kwargs.pop('kelas_wajib', True)
        super().__init__(*args, **kwargs)

        self.tahun_aktif = Tahun_ajaran.objects.filter(status='aktif').order_by('-id').first()
        field_kelas = self.fields['kelas']
        field_kelas.required = kelas_wajib
        field_kelas.label_from_instance = lambda k: k.nama_kelas
        if self.tahun_aktif:
            field_kelas.queryset = Kelas.objects.filter(tahun_ajaran=self.tahun_aktif).order_by('jurusan', 'tingkat', 'nama_kelas')
            field_kelas.help_text = f'Kelas tahun ajaran {self.tahun_aktif.tahun_ajaran}.'
        else:
            field_kelas.help_text = 'Belum ada tahun ajaran aktif, kelas belum bisa dipilih.'

        if self.siswa_id is None:
            self.fields['password'].required = True
        else:
            self.fields['password'].help_text = 'Kosongkan jika tidak ingin mengubah password.'

    def clean_nis(self):
        nis = self.cleaned_data.get('nis')
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

        # Validasi ulang di server kalau filter JS di-bypass: jurusan kelas harus
        # sama dengan jurusan siswa.
        if jurusan and kelas and kelas.jurusan != jurusan:
            self.add_error('kelas', 'Kelas yang dipilih tidak sesuai dengan Jurusan.')
        if self.tahun_aktif is None and self.fields['kelas'].required:
            self.add_error('kelas', 'Belum ada tahun ajaran aktif. Aktifkan tahun ajaran dulu.')

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
    Form yang diisi SISWA SENDIRI. Hanya data kontak: email, no. telepon, alamat.
    NIS, nama, kelas, dan jurusan diisi admin -- SENGAJA tidak ada di form ini
    (ditampilkan sebagai teks read-only dari objek `siswa` di template).

    PENTING: jangan tambahkan field nama/kelas/jurusan ke sini. Kalau ditambah
    sebagai field wajib tapi template tidak merender inputnya, form ini akan
    selalu gagal validasi dan siswa terjebak redirect loop ke "Lengkapi Profil".
    """
    email = forms.EmailField(
        max_length=100,
        widget=forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'contoh@email.com', 'autocomplete': 'email'})
    )
    no_hp = forms.CharField(
        max_length=20,
        label='Nomor Telepon',
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Contoh: 081234567890', 'inputmode': 'tel', 'autocomplete': 'tel'})
    )
    alamat = forms.CharField(
        max_length=255,
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Alamat lengkap tempat tinggal'})
    )

    def clean_no_hp(self):
        import re
        nomor = re.sub(r'[\s\-\.\(\)]', '', self.cleaned_data['no_hp'])
        if not re.fullmatch(r'\+?\d{9,15}', nomor):
            raise forms.ValidationError('Nomor telepon tidak valid. Gunakan 9-15 digit angka, contoh: 081234567890.')
        return nomor

    def clean_alamat(self):
        alamat = ' '.join(self.cleaned_data['alamat'].split())
        if len(alamat) < 10:
            raise forms.ValidationError('Alamat terlalu singkat, tulis alamat selengkapnya.')
        return alamat


SISWA_PASSWORD_MIN_LENGTH = 6


class SiswaPasswordForm(forms.Form):
    """Ganti password oleh siswa sendiri (wajib menyebut password saat ini)."""
    password_lama = forms.CharField(
        label='Password saat ini',
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'autocomplete': 'current-password', 'placeholder': 'Masukkan password saat ini'})
    )
    password_baru = forms.CharField(
        label='Password baru',
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'autocomplete': 'new-password', 'placeholder': f'Minimal {SISWA_PASSWORD_MIN_LENGTH} karakter'})
    )
    konfirmasi_password = forms.CharField(
        label='Konfirmasi password baru',
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'autocomplete': 'new-password', 'placeholder': 'Ulangi password baru'})
    )

    def __init__(self, *args, user=None, siswa=None, **kwargs):
        self.user = user
        self.siswa = siswa
        super().__init__(*args, **kwargs)

    def clean_password_lama(self):
        from django.contrib.auth.hashers import check_password
        lama = self.cleaned_data['password_lama']
        if not check_password(lama, self.user.password):
            raise forms.ValidationError('Password saat ini salah.')
        return lama

    def clean_password_baru(self):
        baru = self.cleaned_data['password_baru']
        if len(baru) < SISWA_PASSWORD_MIN_LENGTH:
            raise forms.ValidationError(f'Password baru minimal {SISWA_PASSWORD_MIN_LENGTH} karakter.')
        terlarang = {self.user.username.lower()}
        if self.siswa is not None:
            terlarang.add(self.siswa.nis.lower())
        if baru.lower() in terlarang:
            raise forms.ValidationError('Password baru tidak boleh sama dengan username atau NIS.')
        return baru

    def clean(self):
        data = super().clean()
        lama, baru, konf = data.get('password_lama'), data.get('password_baru'), data.get('konfirmasi_password')
        if baru and konf and baru != konf:
            self.add_error('konfirmasi_password', 'Konfirmasi password tidak cocok.')
        if lama and baru and lama == baru:
            self.add_error('password_baru', 'Password baru harus berbeda dari password saat ini.')
        return data


TINGKAT_PRESTASI_CHOICES = [
    ('sekolah', 'Sekolah'),
    ('kabupaten/kota', 'Kabupaten/Kota'),
    ('provinsi', 'Provinsi'),
    ('nasional', 'Nasional'),
    ('internasional', 'Internasional'),
]

WILAYAH_PRESTASI_CHOICES = [
    ('dalam_negeri', 'Dalam Negeri'),
    ('luar_negeri', 'Luar Negeri'),
]


class PrestasiUploadForm(forms.Form):
    """
    Form upload prestasi BARU oleh siswa. Wajib melampirkan 2 bukti sekaligus:
    file sertifikat (bukti prestasi) DAN foto dokumentasi -- keduanya wajib,
    tanpa bukti yang lengkap prestasinya tidak ada gunanya untuk diverifikasi.

    Kode & dokumen Puspresnas OPSIONAL dan tersedia di SEMUA tingkat prestasi --
    makanya semua field puspresnas di sini required=False di level form,
    validasinya dicek manual di clean(), bukan lewat required=True biasa.
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
    wilayah_prestasi = forms.ChoiceField(
        label='Wilayah',
        choices=WILAYAH_PRESTASI_CHOICES,
        initial='dalam_negeri',
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

    # ── Kode Puspresnas (di atas bukti prestasi) & file bukti Puspresnas (paling
    #    bawah form), dua-duanya OPSIONAL dan berdiri sendiri-sendiri. ──
    kode_puspresnas = forms.CharField(
        max_length=100, required=False,
        label='Kode Puspresnas (opsional)',
        widget=forms.TextInput(attrs={'class': 'form-control', 'id': 'id_kode_puspresnas', 'placeholder': 'Contoh: PPN-2026-000123'})
    )
    dokumen_puspresnas = forms.FileField(
        required=False,
        label='File Bukti Puspresnas (opsional)',
        validators=[validasi_ukuran_file],
        help_text=f'Maksimal {MAKS_UKURAN_FILE_MB}MB.',
        widget=forms.ClearableFileInput(attrs={'class': 'form-control'})
    )
    jenis_penyelenggara_puspresnas = forms.ChoiceField(
        required=False,
        label='Jenis Penyelenggara (isi jika melampirkan file Puspresnas)',
        choices=[('', '-- Pilih --'), ('kementerian', 'Kementerian'), ('non_kementerian', 'Non-Kementerian (Swasta)')],
        widget=forms.Select(attrs={'class': 'form-select'})
    )

    def clean(self):
        cleaned_data = super().clean()
        dokumen = cleaned_data.get('dokumen_puspresnas')
        penyelenggara_jenis = cleaned_data.get('jenis_penyelenggara_puspresnas')

        # Wilayah dokumen Puspresnas mengikuti field 'Wilayah' prestasi di atas
        # (disalin di view), jadi cukup jenis penyelenggara yang divalidasi.
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
    Form profil yang diisi user KESISWAAN SENDIRI setelah login pertama kali.
    Admin hanya membuat akun (NIP + password). NIP ditampilkan di template
    sebagai teks read-only dan TIDAK ada di form ini -- jadi tidak mungkin
    diubah lewat request POST. Yang bisa diisi/diubah: nama lengkap, nomor
    telepon, dan jabatan. Ketiganya menentukan Kesiswaan.profil_lengkap.
    """
    nama = forms.CharField(
        max_length=100,
        label='Nama Lengkap',
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nama lengkap beserta gelar (jika ada)', 'autocomplete': 'name'})
    )
    no_hp = forms.CharField(
        max_length=20,
        label='Nomor Telepon',
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Contoh: 081234567890', 'inputmode': 'tel', 'autocomplete': 'tel'})
    )
    jabatan = forms.ChoiceField(
        label='Jabatan',
        choices=[('', 'Pilih jabatan...')] + Kesiswaan.JABATAN_CHOICES,
        widget=forms.Select(attrs={'class': 'form-select'})
    )

    def clean_nama(self):
        nama = ' '.join(self.cleaned_data['nama'].split())  # rapikan spasi ganda
        if len(nama) < 3:
            raise forms.ValidationError('Nama lengkap minimal 3 karakter.')
        return nama

    def clean_no_hp(self):
        import re
        nomor = re.sub(r'[\s\-\.\(\)]', '', self.cleaned_data['no_hp'])
        if not re.fullmatch(r'\+?\d{9,15}', nomor):
            raise forms.ValidationError('Nomor telepon tidak valid. Gunakan 9-15 digit angka, contoh: 081234567890.')
        return nomor


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
    wilayah_prestasi = forms.ChoiceField(
        label='Wilayah',
        choices=WILAYAH_PRESTASI_CHOICES,
        initial='dalam_negeri',
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


# =========================================================
# FORM PENGELOLAAN KELAS
# =========================================================

class KelasForm(forms.Form):
    """Form tambah/edit satu baris Kelas untuk sebuah tahun ajaran tertentu."""
    nama_kelas = forms.CharField(
        max_length=100,
        label='Nama Kelas',
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Contoh: XI RPL 1'})
    )
    jurusan = forms.ChoiceField(
        choices=DAFTAR_JURUSAN,
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    tingkat = forms.ChoiceField(
        choices=DAFTAR_TINGKAT,
        widget=forms.Select(attrs={'class': 'form-select'})
    )

    def __init__(self, *args, tahun_ajaran=None, kelas_id=None, **kwargs):
        self.tahun_ajaran = tahun_ajaran
        self.kelas_id = kelas_id
        super().__init__(*args, **kwargs)

    def clean_nama_kelas(self):
        nama_kelas = self.cleaned_data['nama_kelas'].strip()
        qs = Kelas.objects.filter(tahun_ajaran=self.tahun_ajaran, nama_kelas__iexact=nama_kelas)
        if self.kelas_id:
            qs = qs.exclude(id=self.kelas_id)
        if qs.exists():
            raise ValidationError('Sudah ada kelas dengan nama tersebut pada tahun ajaran ini.')
        return nama_kelas


class BuatKelasMassalForm(forms.Form):
    """
    Membuat beberapa kelas sekaligus untuk satu jurusan & tingkat pada satu
    tahun ajaran, contoh: jurusan RPL, tingkat X, jumlah 2 -> otomatis
    membuat "X RPL 1" dan "X RPL 2".
    """
    jurusan = forms.ChoiceField(
        choices=DAFTAR_JURUSAN,
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    tingkat = forms.ChoiceField(
        choices=DAFTAR_TINGKAT,
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    jumlah_kelas = forms.IntegerField(
        min_value=1, max_value=20,
        label='Jumlah Kelas',
        widget=forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Contoh: 2'})
    )

    def __init__(self, *args, tahun_ajaran=None, **kwargs):
        self.tahun_ajaran = tahun_ajaran
        super().__init__(*args, **kwargs)


class SalinKelasForm(forms.Form):
    """Menyalin seluruh daftar Kelas dari satu tahun ajaran ke tahun ajaran lain."""
    tahun_ajaran_sumber = forms.ModelChoiceField(
        queryset=Tahun_ajaran.objects.all(),
        label='Salin Daftar Kelas Dari',
        widget=forms.Select(attrs={'class': 'form-select'})
    )


class NaikkanOtomatisForm(forms.Form):
    """
    Kenaikan kelas XI ke XII secara BAWAAN (kelas dipertahankan sama,
    lihat bagian 7 spesifikasi): tidak ada pembagian ulang, seluruh siswa
    tingkat XI pada tahun ajaran asal otomatis dipindah ke kelas XII dengan
    nama yang sama persis pada tahun ajaran tujuan.
    """
    tahun_ajaran_asal = forms.ModelChoiceField(
        queryset=Tahun_ajaran.objects.all(),
        label='Tahun Ajaran Asal (kelas XI)',
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    jurusan = forms.ChoiceField(
        choices=[('', 'Semua Jurusan')] + list(DAFTAR_JURUSAN),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'})
    )