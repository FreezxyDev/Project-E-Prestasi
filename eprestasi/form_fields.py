"""
Field form siap pakai: sudah membawa sanitasi + aturan validasi + pesan Bahasa Indonesia.

Cukup tulis  `nis = NisField(label='NIS')`  di form -- tidak perlu mengulang aturan di tiap form.
Aturan aslinya ada di `validasi.py`.
"""
from django import forms
from django.core.exceptions import ValidationError
from django.core.validators import MaxLengthValidator, MinLengthValidator, URLValidator

from . import validasi as v


def _pesan_wajib(field, kalimat='wajib diisi', awalan=''):
    """Pesan 'required' berlabel, mis. 'NIS wajib diisi.' / 'Pilih kelas terlebih dahulu.'"""
    if 'required' in (getattr(field, '_pesan_kustom', None) or {}):
        return
    label = (str(field.label) if field.label else '').strip()
    if awalan:
        field.error_messages['required'] = f'{awalan} {label.lower()} terlebih dahulu.' if label else 'Pilihan wajib diisi.'
    else:
        field.error_messages['required'] = f'{label} {kalimat}.' if label else 'Kolom ini wajib diisi.'


def _ganti_validator_panjang(field, min_length=None):
    """Ganti validator panjang bawaan Django (pesan Inggris) dengan pesan Indonesia yang jelas."""
    nama = str(field.label).strip() if field.label else 'Isian'
    field.validators = [x for x in field.validators if not isinstance(x, (MaxLengthValidator, MinLengthValidator))]
    if getattr(field, 'max_length', None):
        field.validators.append(MaxLengthValidator(
            field.max_length, message=f'{nama} maksimal %(limit_value)d karakter (sekarang %(show_value)d).'))
    if min_length:
        field.min_length = min_length
        field.validators.append(MinLengthValidator(
            min_length, message=f'{nama} minimal %(limit_value)d karakter (sekarang %(show_value)d).'))


class TeksField(forms.CharField):
    """
    CharField dengan SANITASI otomatis (spasi berlebih dibuang, karakter tak terlihat & tag HTML
    dibersihkan) SEBELUM divalidasi, sehingga isian yang hanya spasi dianggap kosong (Required).

    Opsi tambahan: placeholder, jenis (data-validasi untuk pesan langsung di browser), attrs,
    multiline (pertahankan baris baru), rows (tinggi textarea), hapus_html.
    """

    def __init__(self, *args, placeholder='', jenis='', attrs=None, multiline=False, rows=3,
                 hapus_html=True, min_length=None, **kwargs):
        self.multiline = multiline
        self.hapus_html = hapus_html
        self._pesan_kustom = kwargs.get('error_messages')
        kwargs['strip'] = False
        if 'widget' not in kwargs:
            atribut = {'class': 'form-control'}
            if placeholder:
                atribut['placeholder'] = placeholder
            if jenis:
                atribut['data-validasi'] = jenis
            atribut.update(attrs or {})
            if multiline:
                atribut['rows'] = str(rows)
                kwargs['widget'] = forms.Textarea(attrs=atribut)
            else:
                kwargs['widget'] = forms.TextInput(attrs=atribut)
        super().__init__(*args, **kwargs)
        _pesan_wajib(self)
        _ganti_validator_panjang(self, min_length)
        if min_length:
            self.widget.attrs.setdefault('minlength', str(min_length))

    def to_python(self, value):
        value = super().to_python(value)
        if value in self.empty_values:
            return self.empty_value
        if self.hapus_html:
            value = v.hapus_tag_html(value)
        value = v.rapikan_paragraf(value) if self.multiline else v.rapikan_spasi(value)
        return value if value else self.empty_value


class NamaField(TeksField):
    """Nama orang: tanpa angka & karakter khusus (lihat validasi.validasi_nama_orang)."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault('max_length', v.NAMA_MAX)
        kwargs.setdefault('min_length', v.NAMA_MIN)
        kwargs.setdefault('jenis', 'nama')
        kwargs.setdefault('attrs', {'autocomplete': 'name'})
        kwargs['validators'] = [v.validasi_nama_orang, *kwargs.get('validators', [])]
        super().__init__(*args, **kwargs)


class NisField(TeksField):
    """NIS: angka saja (tanpa huruf/karakter khusus), 4-20 digit."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault('max_length', v.NIS_MAX + 20)   # beri ruang agar pesan validator yang tampil
        kwargs.setdefault('jenis', 'angka')
        kwargs.setdefault('attrs', {})
        kwargs['attrs'] = {'inputmode': 'numeric', 'data-label': 'NIS',
                           'data-min': str(v.NIS_MIN), 'data-max': str(v.NIS_MAX), **kwargs['attrs']}
        kwargs['validators'] = [v.validasi_nis, *kwargs.get('validators', [])]
        super().__init__(*args, **kwargs)


class NipField(TeksField):
    """NIP: angka saja (tanpa huruf/karakter khusus), 4-20 digit."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault('max_length', v.NIP_MAX + 20)
        kwargs.setdefault('jenis', 'angka')
        kwargs.setdefault('attrs', {})
        kwargs['attrs'] = {'inputmode': 'numeric', 'data-label': 'NIP',
                           'data-min': str(v.NIP_MIN), 'data-max': str(v.NIP_MAX), **kwargs['attrs']}
        kwargs['validators'] = [v.validasi_nip, *kwargs.get('validators', [])]
        super().__init__(*args, **kwargs)


class UsernameField(TeksField):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault('max_length', v.USERNAME_MAX + 20)
        kwargs.setdefault('attrs', {'autocomplete': 'username'})
        kwargs['validators'] = [v.validasi_username, *kwargs.get('validators', [])]
        super().__init__(*args, **kwargs)


class NoHpField(TeksField):
    """Nomor HP seluler Indonesia. Spasi/strip/titik/kurung dibuang otomatis."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault('max_length', 30)
        kwargs.setdefault('jenis', 'hp')
        kwargs.setdefault('attrs', {})
        kwargs['attrs'] = {'inputmode': 'tel', 'autocomplete': 'tel', **kwargs['attrs']}
        kwargs['validators'] = [v.validasi_no_hp, *kwargs.get('validators', [])]
        super().__init__(*args, **kwargs)

    def to_python(self, value):
        value = super().to_python(value)
        return v.normalisasi_no_hp(value) if value else value


class EmailBersihField(forms.EmailField):
    """Email dengan format ketat (wajib '@' dan domain bertitik), otomatis huruf kecil."""
    default_validators = [v.validasi_email]

    def __init__(self, *args, placeholder='contoh@email.com', **kwargs):
        self._pesan_kustom = kwargs.get('error_messages')
        kwargs.setdefault('max_length', v.EMAIL_MAX + 50)
        kwargs.setdefault('widget', forms.EmailInput(attrs={
            'class': 'form-control', 'placeholder': placeholder, 'autocomplete': 'email', 'data-validasi': 'email',
        }))
        super().__init__(*args, **kwargs)
        _pesan_wajib(self)
        _ganti_validator_panjang(self)

    def to_python(self, value):
        value = super().to_python(value)
        # Spasi di tengah sengaja DIPERTAHANKAN supaya validator memberi pesan "tidak boleh mengandung spasi".
        return v.bersihkan_karakter(value).strip().lower()


class URLBersihField(forms.URLField):
    """Tautan: hanya http/https."""
    default_validators = [URLValidator(schemes=['http', 'https'], message='Tautan tidak valid. Contoh: https://contoh.id/halaman')]

    def __init__(self, *args, **kwargs):
        self._pesan_kustom = kwargs.get('error_messages')
        super().__init__(*args, **kwargs)
        self.error_messages['invalid'] = 'Tautan tidak valid. Contoh: https://contoh.id/halaman'
        _pesan_wajib(self)
        _ganti_validator_panjang(self)


class PasswordField(forms.CharField):
    """
    baru=True  -> password BARU: dicek panjang minimal/maksimal & spasi tepi.
    baru=False -> password saat ini / login / konfirmasi: hanya wajib diisi.
    Password TIDAK pernah di-strip/diubah (login memakai nilai apa adanya).
    """

    def __init__(self, *args, baru=True, placeholder='', autocomplete='new-password', css='form-control', **kwargs):
        self._pesan_kustom = kwargs.get('error_messages')
        kwargs['strip'] = False
        kwargs.setdefault('max_length', v.PASSWORD_MAX if not baru else v.PASSWORD_MAX + 50)
        kwargs.setdefault('widget', forms.PasswordInput(attrs={
            'class': css, 'autocomplete': autocomplete,
            **({'placeholder': placeholder} if placeholder else {}),
        }))
        super().__init__(*args, **kwargs)
        _pesan_wajib(self)
        _ganti_validator_panjang(self)
        if baru:
            self.validators.append(v.validasi_password)


class TanggalField(forms.DateField):
    """Tanggal dengan pesan jelas, format input fleksibel, dan opsi rentang/masa depan."""

    def __init__(self, *args, bukan_masa_depan=False, paling_awal=None, paling_akhir=None,
                 umur=None, nama_tanggal=None, **kwargs):
        self._pesan_kustom = kwargs.get('error_messages')
        nama = nama_tanggal or (str(kwargs.get('label')) if kwargs.get('label') else 'Tanggal')
        kwargs.setdefault('input_formats', v.FORMAT_TANGGAL)
        kwargs.setdefault('widget', forms.DateInput(format='%Y-%m-%d', attrs={'class': 'form-control', 'type': 'date'}))
        extra = list(kwargs.pop('validators', []))
        if umur:
            extra.append(v.validasi_tanggal_lahir(*umur))
        else:
            if bukan_masa_depan:
                extra.append(v.validasi_bukan_masa_depan(nama))
            if paling_awal or paling_akhir:
                extra.append(v.validasi_rentang_tanggal(paling_awal, paling_akhir, nama))
        kwargs['validators'] = extra
        super().__init__(*args, **kwargs)
        self.error_messages['invalid'] = 'Tanggal tidak valid. Gunakan format tahun-bulan-tanggal, contoh: 2008-05-17.'
        _pesan_wajib(self)


class AngkaBulatField(forms.IntegerField):
    """Angka bulat dengan rentang min/max dan pesan Indonesia."""

    def __init__(self, *args, **kwargs):
        self._pesan_kustom = kwargs.get('error_messages')
        super().__init__(*args, **kwargs)
        self.error_messages['invalid'] = 'Harus berupa angka bulat (tanpa huruf atau tanda baca).'
        self.error_messages['min_value'] = 'Nilai minimal %(limit_value)s.'
        self.error_messages['max_value'] = 'Nilai maksimal %(limit_value)s.'
        _pesan_wajib(self)


class PilihanField(forms.ChoiceField):
    """ChoiceField: nilai di luar daftar ditolak dengan pesan Indonesia (tidak membocorkan input)."""
    default_error_messages = {'invalid_choice': 'Pilihan tidak valid. Pilih salah satu dari daftar.'}

    def __init__(self, *args, **kwargs):
        self._pesan_kustom = kwargs.get('error_messages')
        super().__init__(*args, **kwargs)
        _pesan_wajib(self, awalan='Pilih')


class RujukanField(forms.ModelChoiceField):
    """Referential validation: pilihan HARUS ada di database (kelas, tahun ajaran, kategori, dst.)."""
    default_error_messages = {'invalid_choice': 'Data yang dipilih tidak terdaftar di sistem. Muat ulang halaman lalu coba lagi.'}

    def __init__(self, *args, **kwargs):
        self._pesan_kustom = kwargs.get('error_messages')
        super().__init__(*args, **kwargs)
        _pesan_wajib(self, awalan='Pilih')


class BerkasField(forms.FileField):
    """File unggahan: ekstensi + isi + ukuran divalidasi (lihat validasi.ValidatorBerkas)."""
    default_error_messages = {
        'invalid': 'File yang dikirim tidak valid.',
        'missing': 'Tidak ada file yang dipilih.',
        'empty': 'File yang diunggah kosong (0 KB).',
        'max_length': 'Nama file terlalu panjang (maksimal %(max)d karakter, sekarang %(length)d).',
        'contradiction': 'Pilih file baru ATAU centang hapus, jangan keduanya.',
    }

    def __init__(self, *args, ekstensi=('pdf', 'jpg', 'jpeg', 'png'), maks_mb=v.MAKS_UKURAN_FILE_MB, **kwargs):
        self._pesan_kustom = kwargs.get('error_messages')
        self.validator_berkas = v.ValidatorBerkas(ekstensi, maks_mb)
        kwargs['validators'] = [self.validator_berkas, *kwargs.get('validators', [])]
        kwargs.setdefault('help_text', f'Format {self.validator_berkas.label_format}, maksimal {maks_mb} MB.')
        kwargs.setdefault('widget', forms.ClearableFileInput(attrs={'class': 'form-control', 'accept': self.validator_berkas.accept}))
        super().__init__(*args, **kwargs)
        _pesan_wajib(self, kalimat='wajib diunggah')


class FotoField(forms.ImageField):
    """Foto JPG/PNG: dicek Pillow (benar-benar gambar) + ekstensi + isi + ukuran."""
    default_error_messages = {
        'invalid': 'File yang dikirim tidak valid.',
        'missing': 'Tidak ada file yang dipilih.',
        'empty': 'File yang diunggah kosong (0 KB).',
        'max_length': 'Nama file terlalu panjang (maksimal %(max)d karakter, sekarang %(length)d).',
        'contradiction': 'Pilih file baru ATAU centang hapus, jangan keduanya.',
        'invalid_image': 'File bukan gambar yang valid atau gambarnya rusak. Unggah foto JPG atau PNG.',
    }

    def __init__(self, *args, ekstensi=('jpg', 'jpeg', 'png'), maks_mb=v.MAKS_UKURAN_FILE_MB, **kwargs):
        self._pesan_kustom = kwargs.get('error_messages')
        self.validator_berkas = v.ValidatorBerkas(ekstensi, maks_mb)
        kwargs['validators'] = [self.validator_berkas, *kwargs.get('validators', [])]
        kwargs.setdefault('help_text', f'Format {self.validator_berkas.label_format}, maksimal {maks_mb} MB.')
        kwargs.setdefault('widget', forms.ClearableFileInput(attrs={'class': 'form-control', 'accept': self.validator_berkas.accept}))
        super().__init__(*args, **kwargs)
        _pesan_wajib(self, kalimat='wajib diunggah')


class DaftarIdField(forms.Field):
    """Kumpulan ID dari checkbox (name=siswa_ids berulang). Nilai bukan angka ditolak, duplikat dibuang."""
    widget = forms.SelectMultiple

    def __init__(self, *args, maksimal=1000, pesan_kosong='Pilih minimal satu data terlebih dahulu.', **kwargs):
        self.maksimal = maksimal
        kwargs.setdefault('error_messages', {'required': pesan_kosong})
        super().__init__(*args, **kwargs)

    def to_python(self, value):
        return v.parse_daftar_id(value, self.maksimal)

    def validate(self, value):
        if self.required and not value:
            raise ValidationError(self.error_messages['required'], code='required')


def kumpulkan_pesan_error(form):
    """Semua pesan error form jadi satu list string (untuk messages.error / JSON)."""
    hasil = []
    for pesan in form.non_field_errors():
        hasil.append(str(pesan))
    for nama, errors in form.errors.items():
        if nama == '__all__':
            continue
        for pesan in errors:
            hasil.append(str(pesan))
    return hasil
