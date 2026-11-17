"""
Aturan validasi & sanitasi TERPUSAT e-Prestasi.

Semua form (admin, siswa, kesiswaan, login, lupa password) memakai aturan dari sini,
jadi satu aturan cukup diubah di satu tempat. File ini sengaja hanya berisi fungsi/aturan
murni (tanpa form/model) supaya mudah dites. Field siap pakai yang membungkus aturan-aturan
ini ada di `form_fields.py`.

Peta jenis validasi -> tempatnya
--------------------------------
Required        : `required=True` di field + sanitasi (isian hanya spasi dianggap kosong)
Type            : `validasi_angka_saja`, `AngkaBulatField`, `ke_int_aman` (parameter URL)
Length          : `min_length`/`max_length` di field, konstanta *_MIN / *_MAX di bawah
Format          : `validasi_email`, `validasi_no_hp`, `validasi_tahun_ajaran`, `validasi_username`
Range           : `validasi_tanggal_lahir` (rentang umur), `AngkaBulatField(min,max)`, rentang tanggal
Uniqueness      : dicek di form (`clean_*`) lewat query ke database
Pattern         : `validasi_nama_orang`, `validasi_nis`, `validasi_nip`, `pola_nomor_dokumen`
Match           : `cocokkan_password` (password & konfirmasi)
File            : `ValidatorBerkas` (ekstensi + isi/tanda file)
Size            : `ValidatorBerkas` (maks_mb)
Date            : `validasi_bukan_masa_depan`, `validasi_rentang_tanggal`, `ke_tanggal_aman`
Cross-field     : `clean()` di form (tanggal mulai <= selesai, jurusan siswa = jurusan kelas, dst.)
Sanitization    : `rapikan_spasi`, `rapikan_paragraf`, `hapus_tag_html`
Referential     : `RujukanField` (ModelChoiceField) + pengecekan ke database di form
"""
import os
import re
import unicodedata
from datetime import date

from django.core.exceptions import ValidationError
from django.utils import timezone

# ──────────────────────────────────────────────────────────────────────────
# KONSTANTA -- ubah di sini, otomatis berlaku ke semua form
# ──────────────────────────────────────────────────────────────────────────
PASSWORD_MIN = 8
PASSWORD_MAX = 128

NIS_MIN, NIS_MAX = 4, 20
NIP_MIN, NIP_MAX = 4, 20

NAMA_MIN, NAMA_MAX = 3, 100          # nama orang (siswa / kesiswaan)
USERNAME_MIN, USERNAME_MAX = 4, 30   # username admin
EMAIL_MAX = 100                      # sama dengan Siswa.email (max_length=100)
NO_HP_MAX = 20

UMUR_SISWA_MIN, UMUR_SISWA_MAX = 12, 30   # rentang umur yang masuk akal untuk siswa
TANGGAL_PRESTASI_PALING_AWAL = date(2000, 1, 1)
TAHUN_AJARAN_PALING_AWAL, TAHUN_AJARAN_PALING_AKHIR = 2000, 2100

MAKS_UKURAN_FILE_MB = 5
MAKS_UKURAN_FILE_BYTES = MAKS_UKURAN_FILE_MB * 1024 * 1024

FORMAT_TANGGAL = ['%Y-%m-%d', '%d/%m/%Y', '%d-%m-%Y']


# ──────────────────────────────────────────────────────────────────────────
# SANITASI -- membersihkan isian sebelum divalidasi/disimpan
# ──────────────────────────────────────────────────────────────────────────
# Karakter kontrol & karakter tak terlihat (zero-width, BOM, pengarah teks) yang sering
# ikut ter-paste dari Word/Excel/WhatsApp. Tab, LF, dan CR sengaja tidak termasuk.
_KARAKTER_TAK_DIINGINKAN = re.compile(
    '[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f\u200b-\u200f\u202a-\u202e\u2060\ufeff]'
)
_TAG_HTML = re.compile(r'<!--.*?-->|</?[A-Za-z][^<>]*>', re.DOTALL)   # hanya tag sungguhan: <b>, </div>, <a href=..>


def _normalisasi(teks):
    teks = unicodedata.normalize('NFC', str(teks))
    return _KARAKTER_TAK_DIINGINKAN.sub('', teks)


def bersihkan_karakter(teks):
    """Buang karakter kontrol/tak terlihat saja (spasi & baris baru tidak diubah)."""
    return _normalisasi(teks) if teks else ''


def rapikan_spasi(teks):
    """'  Budi   Santoso \\n' -> 'Budi Santoso'. Spasi/tab/baris-baru berlebih jadi satu spasi."""
    if teks is None:
        return ''
    return ' '.join(_normalisasi(teks).split())


def rapikan_paragraf(teks):
    """Seperti rapikan_spasi tapi baris baru dipertahankan (maksimal satu baris kosong berturut-turut)."""
    if teks is None:
        return ''
    teks = _normalisasi(teks).replace('\r\n', '\n').replace('\r', '\n')
    baris = [' '.join(b.split()) for b in teks.split('\n')]
    hasil, kosong = [], 0
    for b in baris:
        if b:
            kosong = 0
            hasil.append(b)
        else:
            kosong += 1
            if kosong == 1:
                hasil.append('')
    return '\n'.join(hasil).strip()


def hapus_tag_html(teks):
    """Buang tag HTML utuh seperti <script>...</script>. Tanda '<' tunggal ('5 < 7') dibiarkan."""
    if not teks:
        return teks or ''
    sebelumnya = None
    while sebelumnya != teks:          # ulangi supaya tag bersarang ('<<b>b>') ikut bersih
        sebelumnya = teks
        teks = _TAG_HTML.sub('', teks)
    return teks


def ke_int_aman(nilai, default=None, minimal=None, maksimal=None):
    """Ubah parameter URL/POST jadi int tanpa pernah melempar error. Di luar rentang -> default."""
    teks = str(nilai if nilai is not None else '').strip()
    if not re.fullmatch(r'[0-9]{1,12}', teks):
        return default
    angka = int(teks)
    if (minimal is not None and angka < minimal) or (maksimal is not None and angka > maksimal):
        return default
    return angka


def ke_tanggal_aman(nilai):
    """'2026-13-45' / 'abc' -> None (bukan error 500). Hanya format YYYY-MM-DD."""
    teks = str(nilai or '').strip()
    cocok = re.fullmatch(r'(\d{4})-(\d{2})-(\d{2})', teks)
    if not cocok:
        return None
    try:
        return date(int(cocok[1]), int(cocok[2]), int(cocok[3]))
    except ValueError:
        return None


# ──────────────────────────────────────────────────────────────────────────
# PATTERN & FORMAT
# ──────────────────────────────────────────────────────────────────────────
_HURUF = r'[^\W\d_]'   # satu huruf apa pun (termasuk huruf beraksen), bukan angka/underscore
_POLA_NAMA = re.compile(rf"{_HURUF}(?:{_HURUF}|[ .,'’\-])*")
_POLA_TEMPAT = _POLA_NAMA


def _jumlah_huruf(teks):
    return len(re.findall(_HURUF, teks))


def validasi_nama_orang(nilai):
    """Nama orang: huruf, spasi, titik, koma, apostrof, strip. TIDAK boleh ada angka."""
    if re.search(r'\d', nilai):
        raise ValidationError('Nama tidak boleh mengandung angka.', code='nama_angka')
    if not _POLA_NAMA.fullmatch(nilai):
        raise ValidationError(
            "Nama hanya boleh berisi huruf, spasi, titik (.), koma (,), apostrof (') dan tanda hubung (-). "
            'Karakter khusus lain tidak diperbolehkan.',
            code='nama_karakter',
        )
    if _jumlah_huruf(nilai) < 2:
        raise ValidationError('Nama minimal berisi 2 huruf.', code='nama_pendek')


def validasi_tempat_lahir(nilai):
    if re.search(r'\d', nilai):
        raise ValidationError('Tempat lahir tidak boleh mengandung angka.', code='tempat_angka')
    if not _POLA_TEMPAT.fullmatch(nilai):
        raise ValidationError(
            "Tempat lahir hanya boleh berisi huruf, spasi, titik, koma, apostrof dan tanda hubung.",
            code='tempat_karakter',
        )


def _angka_dengan_panjang(nilai, label, minimal, maksimal):
    if not re.fullmatch(r'[0-9]+', nilai):
        raise ValidationError(
            f'{label} hanya boleh berisi angka (tanpa huruf, spasi, atau karakter khusus).',
            code='angka_saja',
        )
    if len(nilai) < minimal:
        raise ValidationError(f'{label} minimal {minimal} digit (sekarang {len(nilai)}).', code='terlalu_pendek')
    if len(nilai) > maksimal:
        raise ValidationError(f'{label} maksimal {maksimal} digit (sekarang {len(nilai)}).', code='terlalu_panjang')


def validasi_nis(nilai):
    _angka_dengan_panjang(nilai, 'NIS', NIS_MIN, NIS_MAX)


def validasi_nip(nilai):
    _angka_dengan_panjang(nilai, 'NIP', NIP_MIN, NIP_MAX)


_POLA_USERNAME = re.compile(r'[A-Za-z][A-Za-z0-9._\-]*')


def validasi_username(nilai):
    if re.search(r'\s', nilai):
        raise ValidationError('Username tidak boleh mengandung spasi.', code='username_spasi')
    if not _POLA_USERNAME.fullmatch(nilai):
        raise ValidationError(
            'Username harus diawali huruf dan hanya boleh berisi huruf, angka, titik (.), '
            'garis bawah (_), dan tanda hubung (-).',
            code='username_pola',
        )
    if len(nilai) < USERNAME_MIN:
        raise ValidationError(f'Username minimal {USERNAME_MIN} karakter (sekarang {len(nilai)}).', code='username_pendek')
    if len(nilai) > USERNAME_MAX:
        raise ValidationError(f'Username maksimal {USERNAME_MAX} karakter (sekarang {len(nilai)}).', code='username_panjang')


# Email: wajib ada '@', domain wajib memiliki titik + TLD huruf (a@b / a@localhost DITOLAK).
_POLA_EMAIL = re.compile(
    r"[A-Za-z0-9](?:[A-Za-z0-9._%+\-]*[A-Za-z0-9])?"
    r"@(?:[A-Za-z0-9](?:[A-Za-z0-9\-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,24}"
)


def validasi_email(nilai):
    if re.search(r'\s', nilai):
        raise ValidationError('Email tidak boleh mengandung spasi.', code='email_spasi')
    if nilai.count('@') != 1:
        raise ValidationError("Email harus mengandung satu tanda '@'. Contoh: nama@gmail.com", code='email_format')
    lokal = nilai.split('@', 1)[0]
    if '..' in nilai or len(lokal) > 64 or not _POLA_EMAIL.fullmatch(nilai):
        raise ValidationError('Format email tidak valid. Contoh yang benar: nama@gmail.com', code='email_format')
    if len(nilai) > EMAIL_MAX:
        raise ValidationError(f'Email maksimal {EMAIL_MAX} karakter.', code='email_panjang')


def normalisasi_no_hp(nilai):
    """'0812-3456 7890' -> '081234567890' (hapus spasi, strip, titik, kurung)."""
    return re.sub(r'[\s\-.()]', '', nilai or '')


# Nomor seluler Indonesia: 08xx..., +628xx..., atau 628xx... (OTP dikirim lewat WhatsApp).
_POLA_HP = re.compile(r'(?:\+62|62|0)8[1-9][0-9]{7,10}')


def validasi_no_hp(nilai):
    if not re.fullmatch(r'\+?[0-9]+', nilai):
        raise ValidationError('Nomor telepon hanya boleh berisi angka (boleh diawali +).', code='hp_karakter')
    if not _POLA_HP.fullmatch(nilai):
        raise ValidationError(
            'Nomor telepon tidak valid. Gunakan nomor seluler Indonesia 10-13 digit, contoh: 081234567890.',
            code='hp_format',
        )


def validasi_tahun_ajaran(nilai):
    cocok = re.fullmatch(r'(\d{4})/(\d{4})', nilai)
    if not cocok:
        raise ValidationError('Format tahun ajaran harus YYYY/YYYY, contoh: 2025/2026.', code='ta_format')
    awal, akhir = int(cocok[1]), int(cocok[2])
    if akhir != awal + 1:
        raise ValidationError('Tahun kedua harus tepat satu tahun setelah tahun pertama (contoh: 2025/2026).', code='ta_berurutan')
    if not (TAHUN_AJARAN_PALING_AWAL <= awal <= TAHUN_AJARAN_PALING_AKHIR):
        raise ValidationError(
            f'Tahun ajaran harus di antara {TAHUN_AJARAN_PALING_AWAL} dan {TAHUN_AJARAN_PALING_AKHIR}.', code='ta_rentang',
        )


def normalisasi_tahun_ajaran(nilai):
    """'2025 / 2026' -> '2025/2026'."""
    return re.sub(r'\s*/\s*', '/', nilai or '')


def validasi_ada_huruf(nilai):
    """Isian bermakna: minimal mengandung satu huruf (bukan hanya angka/simbol)."""
    if not re.search(_HURUF, nilai):
        raise ValidationError('Isian harus mengandung huruf, tidak boleh hanya angka atau simbol.', code='tanpa_huruf')


def pola_nomor_dokumen(nama='Nomor'):
    """Nomor sertifikat / kode dokumen: huruf, angka, spasi, dan . / - _ , : # ( )"""
    pola = re.compile(r'[A-Za-z0-9 ./\-_,:#()]+')

    def validator(nilai):
        if not pola.fullmatch(nilai):
            raise ValidationError(
                f'{nama} hanya boleh berisi huruf, angka, spasi, dan tanda . / - _ , : # ( )',
                code='dokumen_pola',
            )
    return validator


def validasi_nama_kelas(nilai):
    if not re.fullmatch(r'[A-Za-z0-9 \-]+', nilai):
        raise ValidationError('Nama kelas hanya boleh berisi huruf, angka, spasi, dan tanda hubung (-).', code='kelas_pola')
    if not re.search(r'[A-Za-z]', nilai) or not re.search(r'[0-9]|\b(X|XI|XII)\b', nilai):
        raise ValidationError('Nama kelas tidak lengkap. Contoh: XI RPL 1.', code='kelas_lengkap')


def validasi_kode_jurusan(nilai):
    if not re.fullmatch(r'[A-Z0-9]{2,10}', nilai):
        raise ValidationError('Kode jurusan harus 2-10 karakter huruf/angka tanpa spasi (contoh: PPLG).', code='jurusan_pola')


def validasi_nama_master(nilai):
    """Nama kategori/subkategori prestasi: boleh angka & tanda baca umum, bukan simbol aneh."""
    if not re.fullmatch(r"[^\W_](?:[^\W_]|[ .,'’&/()\-])*", nilai):
        raise ValidationError(
            "Nama hanya boleh berisi huruf, angka, spasi, dan tanda . , ' & / ( ) -",
            code='master_pola',
        )


# ──────────────────────────────────────────────────────────────────────────
# PASSWORD
# ──────────────────────────────────────────────────────────────────────────
def validasi_password(nilai):
    """Aturan password BARU. (Password saat ini/login tidak dicek kekuatannya.)"""
    if len(nilai) < PASSWORD_MIN:
        raise ValidationError(f'Password minimal {PASSWORD_MIN} karakter (sekarang {len(nilai)}).', code='password_pendek')
    if len(nilai) > PASSWORD_MAX:
        raise ValidationError(f'Password maksimal {PASSWORD_MAX} karakter.', code='password_panjang')
    if not nilai.strip():
        raise ValidationError('Password tidak boleh hanya berisi spasi.', code='password_spasi')
    if nilai != nilai.strip():
        raise ValidationError('Password tidak boleh diawali atau diakhiri spasi.', code='password_spasi_tepi')


def cocokkan_password(password, konfirmasi):
    """Match validation. Return pesan error (str) kalau beda, None kalau cocok."""
    if password and konfirmasi and password != konfirmasi:
        return 'Konfirmasi password tidak cocok dengan password.'
    return None


# ──────────────────────────────────────────────────────────────────────────
# TANGGAL
# ──────────────────────────────────────────────────────────────────────────
def hitung_umur(lahir, acuan=None):
    acuan = acuan or timezone.localdate()
    return acuan.year - lahir.year - ((acuan.month, acuan.day) < (lahir.month, lahir.day))


def validasi_bukan_masa_depan(label='Tanggal'):
    def validator(nilai):
        if nilai > timezone.localdate():
            raise ValidationError(f'{label} tidak boleh di masa depan.', code='tanggal_masa_depan')
    return validator


def validasi_rentang_tanggal(paling_awal=None, paling_akhir=None, label='Tanggal'):
    def validator(nilai):
        if paling_awal and nilai < paling_awal:
            raise ValidationError(f'{label} tidak boleh sebelum {paling_awal:%d-%m-%Y}.', code='tanggal_terlalu_awal')
        if paling_akhir and nilai > paling_akhir:
            raise ValidationError(f'{label} tidak boleh setelah {paling_akhir:%d-%m-%Y}.', code='tanggal_terlalu_akhir')
    return validator


def validasi_tanggal_lahir(minimal=UMUR_SISWA_MIN, maksimal=UMUR_SISWA_MAX):
    """Tanggal lahir: tidak di masa depan dan umur berada di rentang [minimal, maksimal] tahun."""
    def validator(nilai):
        if nilai > timezone.localdate():
            raise ValidationError('Tanggal lahir tidak boleh di masa depan.', code='lahir_masa_depan')
        umur = hitung_umur(nilai)
        if umur < minimal or umur > maksimal:
            raise ValidationError(
                f'Tanggal lahir tidak masuk akal (umur {umur} tahun). Umur harus {minimal}-{maksimal} tahun.',
                code='lahir_rentang',
            )
    return validator


# ──────────────────────────────────────────────────────────────────────────
# FILE (jenis + isi + ukuran)
# ──────────────────────────────────────────────────────────────────────────
# Tanda (magic bytes) di awal file. Dipakai supaya file .exe yang diganti namanya jadi .pdf ditolak.
_TANDA_BERKAS = {
    'pdf': (b'%PDF',),
    'jpg': (b'\xff\xd8\xff',),
    'jpeg': (b'\xff\xd8\xff',),
    'png': (b'\x89PNG\r\n\x1a\n',),
    'xlsx': (b'PK\x03\x04',),
}


class ValidatorBerkas:
    """
    Validasi file unggahan: (1) ekstensi diizinkan, (2) isi file sesuai ekstensinya,
    (3) tidak kosong, (4) ukuran tidak melebihi batas.

        ValidatorBerkas(['pdf', 'jpg', 'jpeg', 'png'], maks_mb=5)
    """

    def __init__(self, ekstensi, maks_mb=MAKS_UKURAN_FILE_MB):
        self.ekstensi = tuple(e.lower().lstrip('.') for e in ekstensi)
        self.maks_mb = maks_mb

    @property
    def label_format(self):
        urut = []
        for e in self.ekstensi:
            tampil = 'JPG' if e == 'jpeg' else e.upper()
            if tampil not in urut:
                urut.append(tampil)
        return ', '.join(urut[:-1]) + f' atau {urut[-1]}' if len(urut) > 1 else urut[0]

    @property
    def accept(self):
        """Nilai atribut HTML accept=, mis. '.pdf,.jpg,.jpeg,.png'."""
        return ','.join(f'.{e}' for e in self.ekstensi)

    def __call__(self, berkas):
        nama = getattr(berkas, 'name', '') or ''
        ekstensi = os.path.splitext(nama)[1].lower().lstrip('.')
        if ekstensi not in self.ekstensi:
            dipakai = f'.{ekstensi}' if ekstensi else 'tanpa ekstensi'
            raise ValidationError(
                f'Format file harus {self.label_format}. File kamu: {dipakai}.', code='berkas_format',
            )

        ukuran = getattr(berkas, 'size', None)
        if ukuran == 0:
            raise ValidationError('File kosong (0 KB). Pilih file lain.', code='berkas_kosong')
        if ukuran is not None and ukuran > self.maks_mb * 1024 * 1024:
            raise ValidationError(
                f'Ukuran file maksimal {self.maks_mb} MB. File kamu {ukuran / (1024 * 1024):.1f} MB.',
                code='berkas_besar',
            )

        tanda = _TANDA_BERKAS.get(ekstensi)
        if tanda and hasattr(berkas, 'read'):
            try:
                berkas.seek(0)
                awal = berkas.read(16)
                berkas.seek(0)
            except (OSError, ValueError):
                return
            if not any(awal.startswith(t) for t in tanda):
                raise ValidationError(
                    f'Isi file tidak sesuai dengan ekstensinya (.{ekstensi}). File mungkin rusak atau salah format.',
                    code='berkas_isi',
                )


# ──────────────────────────────────────────────────────────────────────────
# DAFTAR ID (checkbox)
# ──────────────────────────────────────────────────────────────────────────
def parse_daftar_id(nilai_list, maksimal=1000):
    """['3', '3', '7'] -> [3, 7]. Nilai bukan angka -> ValidationError (bukan error 500)."""
    hasil, dilihat = [], set()
    for mentah in nilai_list or []:
        teks = str(mentah).strip()
        if not re.fullmatch(r'[0-9]{1,12}', teks):
            raise ValidationError('Data pilihan tidak valid. Muat ulang halaman lalu coba lagi.', code='id_tidak_valid')
        angka = int(teks)
        if angka not in dilihat:
            dilihat.add(angka)
            hasil.append(angka)
    if len(hasil) > maksimal:
        raise ValidationError(f'Maksimal {maksimal} data sekali proses.', code='id_terlalu_banyak')
    return hasil
