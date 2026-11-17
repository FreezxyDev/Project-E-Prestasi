"""
Semua form e-Prestasi. Aturan validasi & sanitasi ada di `validasi.py`; field siap pakai
(NamaField, NisField, EmailBersihField, TanggalField, BerkasField, dst.) ada di `form_fields.py`.
"""
import re

from django import forms
from django.contrib.auth.hashers import check_password
from django.core.exceptions import ValidationError
from django.utils import timezone

from . import validasi as v
from .form_fields import (
    AngkaBulatField, BerkasField, DaftarIdField, EmailBersihField, FotoField, NamaField, NipField,
    NisField, NoHpField, PasswordField, PilihanField, RujukanField, TanggalField, TeksField,
    URLBersihField, UsernameField,
)
from .models import (
    Siswa, Kesiswaan, Users, Prestasi, Sertifikat, Dokumentasi,
    Kelas, Tahun_ajaran, DAFTAR_JURUSAN, DAFTAR_TINGKAT, Jurusan, LogPerubahanKelas,
    KategoriPrestasi, SubkategoriPrestasi,
    TINGKAT_CHOICES, PEROLEHAN_CHOICES, WILAYAH_PRESTASI_CHOICES as _WILAYAH_MODEL,
)

# Nama lama dipertahankan supaya import lama tidak rusak.
MAKS_UKURAN_FILE_MB = v.MAKS_UKURAN_FILE_MB
MAKS_UKURAN_FILE_BYTES = v.MAKS_UKURAN_FILE_BYTES
PASSWORD_MIN_LENGTH = v.PASSWORD_MIN
SISWA_PASSWORD_MIN_LENGTH = v.PASSWORD_MIN


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


def pilihan_jurusan():
    """
    Referential: daftar jurusan = bawaan + jurusan yang ditambahkan admin di tabel Jurusan.
    Dipakai sebagai callable `choices` sehingga selalu mengikuti isi database.
    """
    hasil = list(DAFTAR_JURUSAN)
    sudah = {k for k, _ in hasil}
    for kode in Jurusan.objects.order_by('kode').values_list('kode', flat=True):
        if kode not in sudah:
            hasil.append((kode, kode))
    return hasil


def _pilihan_jurusan_kosong():
    return [('', '-- Pilih Jurusan --')] + pilihan_jurusan()


def _pilihan_jurusan_semua():
    return [('', 'Semua Jurusan')] + pilihan_jurusan()


def _cek_konfirmasi(form, f_password, f_konfirmasi='konfirmasi_password'):
    """Match validation: password & konfirmasi harus sama."""
    data = form.cleaned_data
    pesan = v.cocokkan_password(data.get(f_password), data.get(f_konfirmasi))
    if pesan:
        form.add_error(f_konfirmasi, pesan)


# =========================================================
# FORM AKUN (ADMIN)
# =========================================================

class SiswaAkunForm(forms.Form):
    """
    Form akun siswa untuk admin. Pilihan Kelas diambil dari model Kelas pada
    TAHUN AJARAN AKTIF (struktur kelas dikelola admin per tahun ajaran di
    Pengelolaan Kelas), bukan daftar tetap. Tingkat ditentukan otomatis dari
    kelas yang dipilih, jadi tidak ada input tingkat di sini.
    """
    nis = NisField(label='NIS', placeholder='Masukkan NIS (angka saja)')
    nama = NamaField(label='Nama Lengkap', placeholder='Masukkan Nama Lengkap (tanpa angka)')
    kelas = RujukanField(
        queryset=Kelas.objects.none(), label='Kelas',
        empty_label='-- Pilih Jurusan dulu --',
        widget=KelasSelectWidget(attrs={'class': 'form-select'}),
    )
    jurusan = PilihanField(
        choices=_pilihan_jurusan_kosong, label='Jurusan',
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    status = PilihanField(
        choices=[('aktif', 'Aktif'), ('alumni', 'Alumni')], required=False, label='Status',
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    password = PasswordField(
        required=False, label='Password', placeholder='Minimal %d karakter' % v.PASSWORD_MIN,
    )  # wajib khusus mode tambah (lihat __init__)
    konfirmasi_password = PasswordField(
        required=False, baru=False, label='Konfirmasi password', placeholder='Ulangi password',
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
            self.fields['konfirmasi_password'].required = True
        else:
            self.fields['password'].help_text = 'Kosongkan jika tidak ingin mengubah password.'

    def clean_nis(self):
        nis = self.cleaned_data.get('nis')
        qs = Siswa.objects.filter(nis=nis)
        if self.siswa_id:
            qs = qs.exclude(id=self.siswa_id)
        if qs.exists():
            raise forms.ValidationError('NIS sudah terdaftar.')
        if Kesiswaan.objects.filter(nip=nis).exists():
            raise forms.ValidationError('NIS ini sudah dipakai sebagai NIP kesiswaan. Gunakan nomor lain.')
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

        if cleaned_data.get('password') and not cleaned_data.get('konfirmasi_password') \
                and 'konfirmasi_password' not in self.errors:
            self.add_error('konfirmasi_password', 'Konfirmasi password wajib diisi.')
        _cek_konfirmasi(self, 'password')
        return cleaned_data


class KesiswaanAkunForm(forms.Form):
    """
    Form akun kesiswaan untuk admin.
    - Mode tambah : hanya NIP + password. Username akun dibuat otomatis dari NIP.
      Nama & jabatan diisi user kesiswaan sendiri setelah login pertama.
    - Mode edit   : admin hanya boleh memperbaiki NIP dan reset password.
    """
    nip = NipField(label='NIP', placeholder='Nomor Induk Pegawai (angka saja)')
    password = PasswordField(
        required=False, label='Password', placeholder='Password awal (min. %d karakter)' % v.PASSWORD_MIN,
        help_text='Kosongkan jika tidak ingin mengubah password.',
    )
    konfirmasi_password = PasswordField(
        required=False, baru=False, label='Konfirmasi password', placeholder='Ulangi password',
    )

    def __init__(self, *args, kesiswaan_id=None, **kwargs):
        self.kesiswaan_id = kesiswaan_id
        super().__init__(*args, **kwargs)
        if kesiswaan_id is None:
            self.fields['password'].required = True
            self.fields['konfirmasi_password'].required = True

    def clean_nip(self):
        nip = self.cleaned_data['nip']
        qs = Kesiswaan.objects.filter(nip=nip)
        if self.kesiswaan_id:
            qs = qs.exclude(id=self.kesiswaan_id)
        if qs.exists():
            raise forms.ValidationError('NIP sudah terdaftar!')
        if Siswa.objects.filter(nis=nip).exists():
            raise forms.ValidationError('NIP ini sudah dipakai sebagai NIS siswa. Periksa kembali nomornya.')
        return nip

    def clean(self):
        data = super().clean()
        if data.get('password') and not data.get('konfirmasi_password') and 'konfirmasi_password' not in self.errors:
            self.add_error('konfirmasi_password', 'Konfirmasi password wajib diisi.')
        _cek_konfirmasi(self, 'password')
        return data


class _TahunAjaranField(TeksField):
    def to_python(self, value):
        # Sanitasi: '2025 / 2026' -> '2025/2026' sebelum divalidasi.
        return v.normalisasi_tahun_ajaran(super().to_python(value))


class TahunAjaranForm(forms.Form):
    tahun_ajaran = _TahunAjaranField(
        max_length=15, label='Tahun Ajaran', placeholder='Contoh: 2025/2026', jenis='tahun-ajaran',
        validators=[v.validasi_tahun_ajaran],
    )
    status = PilihanField(
        choices=[('aktif', 'Aktif'), ('nonaktif', 'Nonaktif')], label='Status',
        widget=forms.Select(attrs={'class': 'form-select'}),
    )

    def __init__(self, *args, tahun_id=None, **kwargs):
        self.tahun_id = tahun_id
        super().__init__(*args, **kwargs)

    def clean_tahun_ajaran(self):
        nilai = self.cleaned_data['tahun_ajaran']
        qs = Tahun_ajaran.objects.filter(tahun_ajaran__iexact=nilai)
        if self.tahun_id:
            qs = qs.exclude(id=self.tahun_id)
        if qs.exists():
            raise forms.ValidationError(f'Tahun ajaran {nilai} sudah terdaftar.')
        return nilai


class AdminAkunForm(forms.Form):
    """
    Form kelola akun admin, hanya bisa diakses super_admin.
    CATATAN: form ini hanya bisa membuat role='admin' (admin biasa).
    Membuat/menaikkan seseorang jadi 'super_admin' sengaja TIDAK disediakan lewat web
    sama sekali -- itu cuma bisa lewat command `python manage.py buat_admin --super`
    di terminal, supaya hak akses tertinggi tidak bisa dibuat lewat form manapun.
    """
    username = UsernameField(label='Username', placeholder='Username login admin (huruf/angka, tanpa spasi)')
    password = PasswordField(
        required=False, label='Password', placeholder='Minimal %d karakter' % v.PASSWORD_MIN,
        help_text='Kosongkan jika tidak ingin mengubah password.',
    )
    konfirmasi_password = PasswordField(
        required=False, baru=False, label='Konfirmasi password', placeholder='Ulangi password',
    )

    def __init__(self, *args, admin_id=None, **kwargs):
        self.admin_id = admin_id
        super().__init__(*args, **kwargs)
        if admin_id is None:
            self.fields['password'].required = True
            self.fields['konfirmasi_password'].required = True

    def clean_username(self):
        username = self.cleaned_data['username']
        qs = Users.objects.filter(username__iexact=username)
        if self.admin_id:
            qs = qs.exclude(id=self.admin_id)
        if qs.exists():
            raise forms.ValidationError('Username telah digunakan!')
        return username

    def clean(self):
        data = super().clean()
        if data.get('password') and not data.get('konfirmasi_password') and 'konfirmasi_password' not in self.errors:
            self.add_error('konfirmasi_password', 'Konfirmasi password wajib diisi.')
        _cek_konfirmasi(self, 'password')
        pw, uname = data.get('password'), data.get('username')
        if pw and uname and pw.lower() == uname.lower():
            self.add_error('password', 'Password tidak boleh sama dengan username.')
        return data


class AdminGantiPasswordForm(forms.Form):
    """Ganti password oleh admin sendiri (wajib menyebut password saat ini)."""
    password_lama = PasswordField(
        baru=False, label='Password saat ini', autocomplete='current-password',
        placeholder='Masukkan password saat ini',
    )
    password_baru = PasswordField(label='Password baru', placeholder=f'Minimal {v.PASSWORD_MIN} karakter')
    konfirmasi_password = PasswordField(baru=False, label='Konfirmasi password baru', placeholder='Ulangi password baru')

    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_password_lama(self):
        lama = self.cleaned_data['password_lama']
        if not check_password(lama, self.user.password):
            raise forms.ValidationError('Password saat ini salah.')
        return lama

    def clean_password_baru(self):
        baru = self.cleaned_data['password_baru']
        if baru.lower() == self.user.username.lower():
            raise forms.ValidationError('Password baru tidak boleh sama dengan username.')
        return baru

    def clean(self):
        data = super().clean()
        _cek_konfirmasi(self, 'password_baru')
        lama, baru = data.get('password_lama'), data.get('password_baru')
        if lama and baru and lama == baru:
            self.add_error('password_baru', 'Password baru harus berbeda dari password saat ini.')
        return data


# =========================================================
# FORM PROFIL & PASSWORD (SISWA / KESISWAAN)
# =========================================================

class SiswaProfilForm(forms.Form):
    """
    Form yang diisi SISWA SENDIRI. Hanya data kontak: email, no. telepon, alamat.
    NIS, nama, kelas, dan jurusan diisi admin -- SENGAJA tidak ada di form ini
    (ditampilkan sebagai teks read-only dari objek `siswa` di template).

    PENTING: jangan tambahkan field nama/kelas/jurusan ke sini. Kalau ditambah
    sebagai field wajib tapi template tidak merender inputnya, form ini akan
    selalu gagal validasi dan siswa terjebak redirect loop ke "Lengkapi Profil".
    """
    email = EmailBersihField(label='Email')
    no_hp = NoHpField(label='Nomor Telepon', placeholder='Contoh: 081234567890')
    # Tempat & tanggal lahir sengaja TIDAK wajib (required=False) supaya siswa lama
    # tidak terkunci di halaman "Lengkapi Profil". Ingin mewajibkan? ubah required=True
    # dan tambahkan kedua field ke Siswa.profil_lengkap.
    tempat_lahir = TeksField(
        max_length=100, required=False, label='Tempat Lahir', placeholder='Contoh: Bandung',
        validators=[v.validasi_tempat_lahir],
    )
    tanggal_lahir = TanggalField(
        required=False, label='Tanggal Lahir', umur=(v.UMUR_SISWA_MIN, v.UMUR_SISWA_MAX),
    )
    alamat = TeksField(
        max_length=255, min_length=10, label='Alamat', multiline=True, rows=3,
        placeholder='Alamat lengkap tempat tinggal (jalan, RT/RW, kelurahan, kota)',
    )

    def clean_alamat(self):
        # Alamat disimpan satu baris (spasi & baris baru dirapikan).
        return v.rapikan_spasi(self.cleaned_data['alamat'])


class SiswaPasswordForm(forms.Form):
    """Ganti password oleh siswa sendiri (wajib menyebut password saat ini)."""
    password_lama = PasswordField(
        baru=False, label='Password saat ini', autocomplete='current-password',
        placeholder='Masukkan password saat ini',
    )
    password_baru = PasswordField(label='Password baru', placeholder=f'Minimal {v.PASSWORD_MIN} karakter')
    konfirmasi_password = PasswordField(baru=False, label='Konfirmasi password baru', placeholder='Ulangi password baru')

    def __init__(self, *args, user=None, siswa=None, **kwargs):
        self.user = user
        self.siswa = siswa
        super().__init__(*args, **kwargs)

    def clean_password_lama(self):
        lama = self.cleaned_data['password_lama']
        if not check_password(lama, self.user.password):
            raise forms.ValidationError('Password saat ini salah.')
        return lama

    def clean_password_baru(self):
        baru = self.cleaned_data['password_baru']
        terlarang = {self.user.username.lower()}
        if self.siswa is not None:
            terlarang.add(self.siswa.nis.lower())
        if baru.lower() in terlarang:
            raise forms.ValidationError('Password baru tidak boleh sama dengan username atau NIS.')
        return baru

    def clean(self):
        data = super().clean()
        _cek_konfirmasi(self, 'password_baru')
        lama, baru = data.get('password_lama'), data.get('password_baru')
        if lama and baru and lama == baru:
            self.add_error('password_baru', 'Password baru harus berbeda dari password saat ini.')
        return data


class LupaPasswordBaruForm(forms.Form):
    """Password baru setelah OTP terverifikasi (lupa password -> tidak ada password lama)."""
    password_baru = PasswordField(label='Password baru', css='input-pill', placeholder=f'Minimal {v.PASSWORD_MIN} karakter')
    konfirmasi_password = PasswordField(
        baru=False, label='Konfirmasi password baru', css='input-pill', placeholder='Ulangi password baru',
    )

    def __init__(self, *args, user=None, siswa=None, **kwargs):
        self.user = user
        self.siswa = siswa
        super().__init__(*args, **kwargs)

    def clean_password_baru(self):
        baru = self.cleaned_data['password_baru']
        terlarang = {self.user.username.lower()}
        if self.siswa is not None:
            terlarang.add(self.siswa.nis.lower())
        if baru.lower() in terlarang:
            raise forms.ValidationError('Password baru tidak boleh sama dengan username atau NIS.')
        return baru

    def clean(self):
        data = super().clean()
        _cek_konfirmasi(self, 'password_baru')
        return data


class KesiswaanProfilForm(forms.Form):
    """
    Form profil yang diisi user KESISWAAN SENDIRI setelah login pertama kali.
    Admin hanya membuat akun (NIP + password). NIP ditampilkan di template
    sebagai teks read-only dan TIDAK ada di form ini -- jadi tidak mungkin
    diubah lewat request POST. Yang bisa diisi/diubah: nama lengkap, nomor
    telepon, dan jabatan. Ketiganya menentukan Kesiswaan.profil_lengkap.
    """
    nama = NamaField(label='Nama Lengkap', placeholder='Nama lengkap beserta gelar (jika ada), tanpa angka')
    no_hp = NoHpField(label='Nomor Telepon', placeholder='Contoh: 081234567890')
    jabatan = PilihanField(
        label='Jabatan',
        choices=[('', 'Pilih jabatan...')] + Kesiswaan.JABATAN_CHOICES,
        widget=forms.Select(attrs={'class': 'form-select'}),
    )


class KesiswaanPasswordForm(forms.Form):
    """Ganti password oleh kesiswaan sendiri (field `konfirmasi` sesuai template lengkapi_profil)."""
    password_lama = PasswordField(
        baru=False, label='Password saat ini', autocomplete='current-password',
        placeholder='Masukkan password saat ini',
    )
    password_baru = PasswordField(label='Password baru', placeholder=f'Minimal {v.PASSWORD_MIN} karakter')
    konfirmasi = PasswordField(baru=False, label='Konfirmasi password baru', placeholder='Ulangi password baru')

    def __init__(self, *args, user=None, kesiswaan=None, **kwargs):
        self.user = user
        self.kesiswaan = kesiswaan
        super().__init__(*args, **kwargs)

    def clean_password_lama(self):
        lama = self.cleaned_data['password_lama']
        if not check_password(lama, self.user.password):
            raise forms.ValidationError('Password saat ini salah.')
        return lama

    def clean_password_baru(self):
        baru = self.cleaned_data['password_baru']
        terlarang = {self.user.username.lower()}
        if self.kesiswaan is not None:
            terlarang.add(self.kesiswaan.nip.lower())
        if baru.lower() in terlarang:
            raise forms.ValidationError('Password baru tidak boleh sama dengan username atau NIP.')
        return baru

    def clean(self):
        data = super().clean()
        _cek_konfirmasi(self, 'password_baru', 'konfirmasi')
        lama, baru = data.get('password_lama'), data.get('password_baru')
        if lama and baru and lama == baru:
            self.add_error('password_baru', 'Password baru harus berbeda dari password saat ini.')
        return data


# =========================================================
# FORM LOGIN & LUPA PASSWORD
# =========================================================

class LoginForm(forms.Form):
    """Hanya memastikan terisi & wajar (tanpa aturan pola, karena akun lama bisa berformat apa saja)."""
    username = TeksField(max_length=100, label='Username / NIS / NIP', hapus_html=False)
    password = PasswordField(baru=False, label='Password', autocomplete='current-password')


class LupaPasswordCariForm(forms.Form):
    identitas = TeksField(max_length=100, label='NIS / Username', hapus_html=False)


class OtpForm(forms.Form):
    kode = TeksField(max_length=12, label='Kode OTP', hapus_html=False)

    def clean_kode(self):
        digit = re.sub(r'\D', '', self.cleaned_data['kode'])
        if len(digit) != 6:
            raise forms.ValidationError('Kode OTP harus 6 digit angka.')
        return digit


class CatatanForm(forms.Form):
    """Catatan singkat opsional (mis. alasan menolak permintaan reset password)."""
    catatan = TeksField(max_length=255, required=False, label='Catatan', multiline=True)


# =========================================================
# FORM PRESTASI
# =========================================================

# Sumber tunggal ada di models.TINGKAT_CHOICES (nama lama dipertahankan untuk import lama).
TINGKAT_PRESTASI_CHOICES = TINGKAT_CHOICES

# Diambil dari model (sumber tunggal) supaya nilai di form = nilai yang boleh tersimpan di database.
WILAYAH_PRESTASI_CHOICES = list(_WILAYAH_MODEL)


class SubkategoriSelect(forms.Select):
    """Select subkategori; tiap <option> membawa data-kategori & data-lainnya untuk JavaScript."""
    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex, attrs)
        instance = getattr(value, 'instance', None)
        if instance is not None:
            option['attrs']['data-kategori'] = instance.kategori.kode
            option['attrs']['data-kelompok'] = instance.kelompok
            option['attrs']['data-nama'] = instance.nama
            option['attrs']['data-lainnya'] = '1' if instance.adalah_lainnya else '0'
        return option


class SubkategoriChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return obj.nama_lengkap


def _pilihan_kategori():
    """Kategori aktif dari master; kalau master belum terisi, pakai dua kategori bawaan."""
    pilihan = list(KategoriPrestasi.objects.filter(aktif=True).values_list('kode', 'nama'))
    return pilihan or [('akademik', 'Akademik'), ('non-akademik', 'Non-Akademik')]


def data_subkategori():
    """
    Data untuk JavaScript form (dependent dropdown), dikirim lewat json_script:
    {kode_kategori: [{id, nama, kelompok, lainnya}, ...]}.
    """
    hasil = {}
    for sub in SubkategoriPrestasi.objects.filter(aktif=True, kategori__aktif=True).select_related('kategori'):
        hasil.setdefault(sub.kategori.kode, []).append({
            'id': sub.pk, 'nama': sub.nama, 'kelompok': sub.kelompok, 'lainnya': sub.adalah_lainnya,
        })
    return hasil


def konfigurasi_form_prestasi():
    """Paket konteks untuk template form prestasi (daftar subkategori per kategori)."""
    return {
        'data_subkategori': data_subkategori(),
    }



class PrestasiDataForm(forms.Form):
    """
    Bagian DATA prestasi yang dipakai bersama oleh form pengajuan baru dan form
    perbaikan data. Menjaga konsistensi: kategori <-> subkategori,
    tanggal tidak di masa depan, dan "Lainnya" wajib diketik.
    """
    nama_prestasi = TeksField(
        max_length=100, min_length=3, label='Nama kegiatan / kompetisi',
        placeholder='Contoh: Lomba Kompetensi Siswa (LKS) Web Technologies',
        validators=[v.validasi_ada_huruf],
    )
    kategori_prestasi = PilihanField(
        choices=[], label='Kategori',
        widget=forms.Select(attrs={'class': 'form-select', 'id': 'id_kategori_prestasi'}),
    )
    subkategori = SubkategoriChoiceField(
        queryset=SubkategoriPrestasi.objects.none(), label='Subkategori',
        empty_label='-- Pilih subkategori --',
        widget=SubkategoriSelect(attrs={'class': 'form-select', 'id': 'id_subkategori'}),
    )
    subkategori_lainnya = TeksField(
        max_length=100, required=False, label='Sebutkan bidangnya',
        attrs={'id': 'id_subkategori_lainnya'}, placeholder='Contoh: Catur',
        validators=[v.validasi_ada_huruf],
    )
    penyelenggara = TeksField(
        max_length=100, min_length=3, label='Penyelenggara',
        placeholder='Contoh: Dinas Pendidikan Provinsi Jawa Barat',
        validators=[v.validasi_ada_huruf],
    )
    wilayah_prestasi = PilihanField(
        label='Wilayah penyelenggaraan', choices=[('', '-- Pilih wilayah --')] + WILAYAH_PRESTASI_CHOICES,
        widget=forms.Select(attrs={'class': 'form-select', 'id': 'id_wilayah_prestasi'}),
    )
    tingkat_prestasi = PilihanField(
        label='Tingkat', choices=TINGKAT_PRESTASI_CHOICES,
        widget=forms.Select(attrs={'class': 'form-select', 'id': 'id_tingkat_prestasi'}),
    )
    jenis_perolehan = PilihanField(
        label='Perolehan', choices=[('', '-- Pilih perolehan --')] + PEROLEHAN_CHOICES,
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    tanggal_mulai = TanggalField(
        required=False, label='Tanggal mulai (jika kegiatan lebih dari 1 hari)',
        nama_tanggal='Tanggal mulai', bukan_masa_depan=True, paling_awal=v.TANGGAL_PRESTASI_PALING_AWAL,
    )
    tanggal_prestasi = TanggalField(
        label='Tanggal pelaksanaan / pengumuman hasil',
        nama_tanggal='Tanggal pelaksanaan', bukan_masa_depan=True, paling_awal=v.TANGGAL_PRESTASI_PALING_AWAL,
    )
    nomor_sertifikat = TeksField(
        max_length=100, required=False, label='Nomor sertifikat / piagam (jika ada)',
        placeholder='Contoh: 123/SERT/2026',
        validators=[v.pola_nomor_dokumen('Nomor sertifikat')],
    )
    tautan_pendukung = URLBersihField(
        max_length=500, required=False, label='Tautan pendukung (opsional)',
        widget=forms.URLInput(attrs={'class': 'form-control', 'placeholder': 'https://...'}),
    )
    deskripsi = TeksField(
        max_length=2000, min_length=10, label='Deskripsi', multiline=True, rows=4,
        placeholder='Ceritakan sedikit tentang prestasi ini (minimal 10 karakter)',
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['kategori_prestasi'].choices = _pilihan_kategori()
        self.fields['subkategori'].queryset = (
            SubkategoriPrestasi.objects.filter(aktif=True, kategori__aktif=True).select_related('kategori')
        )

    def clean(self):
        data = super().clean()
        kategori = data.get('kategori_prestasi')
        sub = data.get('subkategori')
        mulai = data.get('tanggal_mulai')
        tanggal = data.get('tanggal_prestasi')

        if sub is not None and kategori and sub.kategori.kode != kategori:
            self.add_error('subkategori', 'Subkategori tidak sesuai dengan kategori yang dipilih.')
        if sub is not None:
            if sub.adalah_lainnya:
                teks = ' '.join((data.get('subkategori_lainnya') or '').split())
                if not teks and 'subkategori_lainnya' not in self.errors:
                    self.add_error('subkategori_lainnya', 'Sebutkan bidang prestasinya karena kamu memilih "Lainnya".')
                data['subkategori_lainnya'] = teks
            else:
                data['subkategori_lainnya'] = ''

        # Cross-field: tanggal mulai tidak boleh setelah tanggal pelaksanaan.
        # (Tanggal masa depan sudah ditolak di level field oleh TanggalField.)
        if mulai and tanggal and mulai > tanggal:
            self.add_error('tanggal_mulai', 'Tanggal mulai tidak boleh setelah tanggal pelaksanaan.')
        return data


class PrestasiUploadForm(PrestasiDataForm):
    """
    Form pengajuan prestasi BARU oleh siswa.

    Bukti: MINIMAL SATU dari sertifikat/piagam, foto dokumentasi, atau tautan
    pendukung (tidak lagi mewajibkan sertifikat DAN foto sekaligus). Kebijakan
    sekolah bisa mengubah syaratnya di method clean() ini.

    Kode & dokumen Puspresnas tetap OPSIONAL dan berdiri sendiri.
    File divalidasi jenis (PDF/JPG/PNG), isi, dan ukurannya (lihat BerkasField/FotoField).
    """
    # ── Bukti (minimal satu) ──
    file_sertifikat = BerkasField(required=False, label='Sertifikat / piagam')
    deskripsi_sertifikat = TeksField(
        max_length=255, required=False, label='Keterangan bukti prestasi (opsional)',
        placeholder='Contoh: Sertifikat asli, halaman depan',
    )
    foto_dokumentasi = FotoField(required=False, label='Foto kegiatan / dokumentasi')
    caption_dokumentasi = TeksField(
        max_length=100, required=False, label='Keterangan dokumentasi (opsional)',
        placeholder='Contoh: Foto saat penyerahan piala',
    )

    # ── Kode Puspresnas & file bukti Puspresnas, dua-duanya OPSIONAL ──
    kode_puspresnas = TeksField(
        max_length=100, required=False, label='Kode Puspresnas (opsional)',
        attrs={'id': 'id_kode_puspresnas'}, placeholder='Contoh: PPN-2026-000123',
        validators=[v.pola_nomor_dokumen('Kode Puspresnas')],
    )
    dokumen_puspresnas = BerkasField(required=False, label='File Bukti Puspresnas (opsional)')
    jenis_penyelenggara_puspresnas = PilihanField(
        required=False,
        label='Jenis Penyelenggara (isi jika melampirkan file Puspresnas)',
        choices=[('', '-- Pilih --'), ('kementerian', 'Kementerian'), ('non_kementerian', 'Non-Kementerian (Swasta)')],
        widget=forms.Select(attrs={'class': 'form-select'}),
    )

    pernyataan = forms.BooleanField(
        required=True,
        label='Saya menyatakan bahwa data dan bukti yang saya ajukan adalah benar.',
        error_messages={'required': 'Centang pernyataan ini sebelum mengirim pengajuan.'},
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
    )

    def clean(self):
        cleaned_data = super().clean()
        dokumen = cleaned_data.get('dokumen_puspresnas')
        penyelenggara_jenis = cleaned_data.get('jenis_penyelenggara_puspresnas')

        # Wilayah dokumen Puspresnas mengikuti field 'Wilayah' prestasi (disalin di view),
        # jadi cukup jenis penyelenggara yang divalidasi.
        if dokumen and not penyelenggara_jenis:
            self.add_error('jenis_penyelenggara_puspresnas', 'Wajib dipilih kalau melampirkan dokumen Puspresnas.')

        ada_bukti = any([
            cleaned_data.get('file_sertifikat'),
            cleaned_data.get('foto_dokumentasi'),
            cleaned_data.get('tautan_pendukung'),
        ])
        # Hanya tampilkan error ini kalau field bukti sendiri tidak error (mis. file kebesaran).
        error_bukti = any(k in self.errors for k in ('file_sertifikat', 'foto_dokumentasi', 'tautan_pendukung'))
        if not ada_bukti and not error_bukti:
            raise ValidationError(
                'Lampirkan minimal satu bukti prestasi: sertifikat/piagam, foto dokumentasi, atau tautan pendukung.'
            )
        return cleaned_data


class SertifikatTambahanForm(forms.Form):
    """Dipakai buat nambah bukti sertifikat SUSULAN ke prestasi yang sudah ada."""
    file = BerkasField(label='File Sertifikat')
    deskripsi = TeksField(max_length=255, required=False, label='Keterangan', placeholder='Opsional')


class DokumentasiTambahanForm(forms.Form):
    """Dipakai buat nambah foto dokumentasi (bukan sertifikat resmi, tapi foto kegiatan/lomba)."""
    foto = FotoField(label='Foto dokumentasi')
    caption = TeksField(max_length=100, required=False, label='Keterangan', placeholder='Opsional')


class VerifikasiPrestasiForm(forms.Form):
    """
    Form keputusan verifikasi oleh kesiswaan. Ada 3 pilihan keputusan:
    - diterima  : prestasi lolos verifikasi, langsung tampil di portofolio publik.
    - perbaikan : dikembalikan ke siswa untuk diperbaiki (data atau file),
                  wajib pilih jenis_perbaikan + isi catatan_perbaikan.
    - ditolak   : ditolak permanen, wajib isi alasan_penolakan.
    """
    keputusan = PilihanField(
        choices=[('diterima', 'Terima'), ('perbaikan', 'Perbaiki'), ('ditolak', 'Tolak')],
        label='Keputusan', widget=forms.RadioSelect,
    )
    jenis_perbaikan = PilihanField(
        choices=[('data', 'Perbaikan Data'), ('file', 'Perbaikan File')],
        required=False, label='Jenis perbaikan', widget=forms.RadioSelect,
    )
    catatan_perbaikan = TeksField(
        required=False, max_length=1000, min_length=5, label='Catatan perbaikan', multiline=True,
        placeholder='Jelaskan apa yang perlu diperbaiki siswa, wajib diisi kalau memilih Perbaiki',
    )
    alasan_penolakan = TeksField(
        required=False, max_length=1000, min_length=5, label='Alasan penolakan', multiline=True,
        placeholder='Wajib diisi kalau prestasi ditolak',
    )

    def clean(self):
        cleaned_data = super().clean()
        keputusan = cleaned_data.get('keputusan')
        alasan = (cleaned_data.get('alasan_penolakan') or '').strip()
        jenis_perbaikan = cleaned_data.get('jenis_perbaikan')
        catatan = (cleaned_data.get('catatan_perbaikan') or '').strip()

        if keputusan == 'ditolak' and not alasan and 'alasan_penolakan' not in self.errors:
            self.add_error('alasan_penolakan', 'Alasan penolakan wajib diisi kalau prestasi ditolak.')

        if keputusan == 'perbaikan':
            if not jenis_perbaikan:
                self.add_error('jenis_perbaikan', 'Pilih jenis perbaikan (data atau file).')
            if not catatan and 'catatan_perbaikan' not in self.errors:
                self.add_error('catatan_perbaikan', 'Catatan perbaikan wajib diisi supaya siswa tahu apa yang harus diperbaiki.')

        return cleaned_data


class PrestasiEditForm(PrestasiDataForm):
    """
    Dipakai siswa untuk memperbaiki DATA prestasi yang dikembalikan kesiswaan
    dengan jenis_perbaikan='data' (tidak termasuk file -- file sertifikat lama
    tetap ada, tidak perlu upload ulang).
    """


class LengkapiDataPrestasiForm(forms.Form):
    """
    Dipakai KESISWAAN untuk melengkapi klasifikasi prestasi (terutama data lama yang
    dibuat sebelum ada subkategori & perolehan). Setiap perubahan dicatat di riwayat.
    """
    subkategori = SubkategoriChoiceField(
        queryset=SubkategoriPrestasi.objects.none(), required=False, label='Subkategori',
        empty_label='-- Tidak diubah --',
        widget=SubkategoriSelect(attrs={'class': 'form-select'}),
    )
    subkategori_lainnya = TeksField(
        max_length=100, required=False, label='Sebutkan bidangnya', validators=[v.validasi_ada_huruf],
    )
    jenis_perolehan = PilihanField(
        required=False, label='Perolehan', choices=[('', '-- Tidak diubah --')] + PEROLEHAN_CHOICES,
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    nomor_sertifikat = TeksField(
        max_length=100, required=False, label='Nomor sertifikat',
        validators=[v.pola_nomor_dokumen('Nomor sertifikat')],
    )

    def __init__(self, *args, prestasi=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.prestasi = prestasi
        qs = SubkategoriPrestasi.objects.filter(aktif=True, kategori__aktif=True).select_related('kategori')
        if prestasi is not None:
            # Subkategori harus sesuai kategori prestasi itu (kalau kategorinya ada di master).
            if KategoriPrestasi.objects.filter(kode=prestasi.kategori_prestasi).exists():
                qs = qs.filter(kategori__kode=prestasi.kategori_prestasi)
        self.fields['subkategori'].queryset = qs

    def clean(self):
        data = super().clean()
        sub = data.get('subkategori')
        if sub is not None:
            if sub.adalah_lainnya:
                teks = ' '.join((data.get('subkategori_lainnya') or '').split())
                if not teks and 'subkategori_lainnya' not in self.errors:
                    self.add_error('subkategori_lainnya', 'Sebutkan bidangnya karena memilih "Lainnya".')
                data['subkategori_lainnya'] = teks
            else:
                data['subkategori_lainnya'] = ''
        return data


# =========================================================
# FORM IMPORT & PENGELOLAAN KELAS (ADMIN)
# =========================================================

class ImportSiswaForm(forms.Form):
    """Form upload file Excel (.xlsx) buat bikin banyak akun siswa sekaligus."""
    file_excel = BerkasField(
        label='File Excel (.xlsx)', ekstensi=('xlsx',),
        widget=forms.ClearableFileInput(attrs={'class': 'form-control', 'accept': '.xlsx'}),
    )


class _KodeField(TeksField):
    """Kode singkat: spasi dibuang & huruf kapital (mis. 'pplg' -> 'PPLG')."""
    def to_python(self, value):
        return re.sub(r'\s+', '', super().to_python(value)).upper()


class KelasForm(forms.Form):
    """Form tambah/edit satu baris Kelas untuk sebuah tahun ajaran tertentu."""
    nama_kelas = TeksField(
        max_length=100, min_length=3, label='Nama Kelas', placeholder='Contoh: XI RPL 1',
        validators=[v.validasi_nama_kelas],
    )
    jurusan = PilihanField(choices=pilihan_jurusan, label='Jurusan', widget=forms.Select(attrs={'class': 'form-select'}))
    tingkat = PilihanField(choices=DAFTAR_TINGKAT, label='Tingkat', widget=forms.Select(attrs={'class': 'form-select'}))

    def __init__(self, *args, tahun_ajaran=None, kelas_id=None, **kwargs):
        self.tahun_ajaran = tahun_ajaran
        self.kelas_id = kelas_id
        super().__init__(*args, **kwargs)

    def clean_nama_kelas(self):
        nama_kelas = self.cleaned_data['nama_kelas']
        if self.tahun_ajaran is None:
            raise ValidationError('Tahun ajaran belum dipilih atau tidak terdaftar.')
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
    membuat "X RPL 1" dan "X RPL 2". `nama_kustom` (opsional) menggantikan kode
    jurusan di nama kelas, mis. 'PPLG' -> "X PPLG 1".
    """
    jurusan = PilihanField(choices=pilihan_jurusan, label='Jurusan', widget=forms.Select(attrs={'class': 'form-select'}))
    tingkat = PilihanField(choices=DAFTAR_TINGKAT, label='Tingkat', widget=forms.Select(attrs={'class': 'form-select'}))
    nama_kustom = _KodeField(
        max_length=10, required=False, label='Nama kustom (opsional)',
        validators=[v.validasi_kode_jurusan],
    )
    jumlah_kelas = AngkaBulatField(
        min_value=1, max_value=20, label='Jumlah Kelas',
        widget=forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Contoh: 2', 'min': 1, 'max': 20}),
    )

    def __init__(self, *args, tahun_ajaran=None, **kwargs):
        self.tahun_ajaran = tahun_ajaran
        super().__init__(*args, **kwargs)

    def clean(self):
        data = super().clean()
        if self.tahun_ajaran is None:
            raise ValidationError('Tahun ajaran belum dipilih atau tidak terdaftar.')
        return data


class JurusanBaruForm(forms.Form):
    """Tambah jurusan baru: kode 2-10 karakter huruf/angka, tidak boleh kembar."""
    kode_jurusan = _KodeField(max_length=20, label='Kode jurusan', validators=[v.validasi_kode_jurusan])

    def clean_kode_jurusan(self):
        kode = self.cleaned_data['kode_jurusan']
        if kode in {k for k, _ in DAFTAR_JURUSAN} or Jurusan.objects.filter(kode__iexact=kode).exists():
            raise ValidationError(f'Jurusan {kode} sudah ada.')
        return kode


class SalinKelasForm(forms.Form):
    """Menyalin seluruh daftar Kelas dari satu tahun ajaran ke tahun ajaran lain."""
    tahun_ajaran_sumber = RujukanField(
        queryset=Tahun_ajaran.objects.all(), label='Tahun ajaran sumber',
        widget=forms.Select(attrs={'class': 'form-select'}),
    )

    def __init__(self, *args, tahun_tujuan=None, **kwargs):
        self.tahun_tujuan = tahun_tujuan
        super().__init__(*args, **kwargs)

    def clean_tahun_ajaran_sumber(self):
        sumber = self.cleaned_data['tahun_ajaran_sumber']
        if self.tahun_tujuan is not None and sumber.pk == self.tahun_tujuan.pk:
            raise ValidationError('Tahun ajaran sumber tidak boleh sama dengan tahun ajaran tujuan.')
        return sumber


class NaikkanOtomatisForm(forms.Form):
    """
    Kenaikan kelas XI ke XII secara BAWAAN (kelas dipertahankan sama,
    lihat bagian 7 spesifikasi): tidak ada pembagian ulang, seluruh siswa
    tingkat XI pada tahun ajaran asal otomatis dipindah ke kelas XII dengan
    nama yang sama persis pada tahun ajaran tujuan.
    """
    tahun_ajaran_asal = RujukanField(
        queryset=Tahun_ajaran.objects.all(), label='Tahun Ajaran Asal (kelas XI)',
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    jurusan = PilihanField(
        choices=_pilihan_jurusan_semua, required=False, label='Jurusan',
        widget=forms.Select(attrs={'class': 'form-select'}),
    )

    def __init__(self, *args, tahun_tujuan=None, **kwargs):
        self.tahun_tujuan = tahun_tujuan
        super().__init__(*args, **kwargs)

    def clean_tahun_ajaran_asal(self):
        asal = self.cleaned_data['tahun_ajaran_asal']
        if self.tahun_tujuan is not None and asal.pk == self.tahun_tujuan.pk:
            raise ValidationError('Tahun ajaran asal tidak boleh sama dengan tahun ajaran tujuan.')
        return asal


class TempatkanSiswaForm(forms.Form):
    """Penempatan/pemindahan siswa ke kelas tertentu (semua referensi harus ada di database)."""
    tahun_ajaran = RujukanField(queryset=Tahun_ajaran.objects.all(), label='Tahun ajaran')
    kelas_tujuan = RujukanField(queryset=Kelas.objects.all(), label='Kelas tujuan')
    siswa_ids = DaftarIdField(pesan_kosong='Pilih minimal satu siswa terlebih dahulu.')
    jenis_perubahan = PilihanField(
        choices=LogPerubahanKelas.JENIS_PERUBAHAN_CHOICES, required=False, label='Jenis perubahan',
    )
    alasan_perubahan = TeksField(max_length=500, required=False, label='Alasan perubahan', multiline=True)
    mode_manual_xii = forms.BooleanField(required=False)

    def clean(self):
        data = super().clean()
        ta, kelas = data.get('tahun_ajaran'), data.get('kelas_tujuan')
        if ta and kelas and kelas.tahun_ajaran_id != ta.pk:
            self.add_error('kelas_tujuan', 'Kelas tujuan bukan milik tahun ajaran yang dipilih.')
        return data


class CekNisMassalForm(forms.Form):
    tahun_ajaran = RujukanField(queryset=Tahun_ajaran.objects.all(), label='Tahun ajaran')
    nis_list = TeksField(max_length=40000, label='Daftar NIS', multiline=True, hapus_html=False)


class KeluarkanSiswaForm(forms.Form):
    """Mencatat siswa keluar/dikeluarkan (status berubah jadi non-aktif)."""
    jenis_keluar = PilihanField(choices=Siswa.JENIS_KELUAR_CHOICES, label='Jenis keluar')
    tanggal_keluar = TanggalField(
        required=False, label='Tanggal keluar', bukan_masa_depan=True, paling_awal=v.TANGGAL_PRESTASI_PALING_AWAL,
    )
    keterangan_keluar = TeksField(max_length=500, required=False, label='Keterangan', multiline=True)


class MasterNamaForm(forms.Form):
    """Nama kategori / subkategori prestasi (master data)."""
    nama = TeksField(max_length=100, min_length=2, label='Nama', validators=[v.validasi_nama_master])


class MasterSubkategoriForm(MasterNamaForm):
    kategori_id = RujukanField(queryset=KategoriPrestasi.objects.all(), label='Kategori')
    kelompok = TeksField(max_length=100, required=False, label='Kelompok', validators=[v.validasi_nama_master])


class MasterAksiForm(forms.Form):
    """Id data master untuk aksi ubah-nama / aktif-nonaktif / hapus."""
    id = AngkaBulatField(min_value=1, label='Data')
