import hashlib
import logging
from datetime import timedelta

from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth.hashers import check_password
from django.db import transaction
from django.utils import timezone

from .models import (
    Users,
    Siswa,
    Kesiswaan,
    LoginAttempt,
    NPSN_SMKN_11_BANDUNG,
)

logger = logging.getLogger(__name__)


# =========================================================
# PEMBATASAN PERCOBAAN LOGIN
# =========================================================

# Batas per AKUN (ketat)
MAKS_PERCOBAAN_GAGAL = 5

# Batas per IP (longgar, supaya satu sekolah di satu IP tetap aman)
MAKS_GAGAL_PER_IP = 50

DURASI_KUNCI = timedelta(minutes=15)
JENDELA_HITUNG = timedelta(minutes=15)


# =========================================================
# MENGAMBIL IP KLIEN
# =========================================================

def _ip_klien(request):
    """
    Mengambil IP klien.
    Urutan:
    1. CF-Connecting-IP
    2. X-Forwarded-For (entri pertama)
    3. REMOTE_ADDR

    Catatan: header CF-Connecting-IP dan X-Forwarded-For bisa dipalsukan
    jika server dapat diakses langsung tanpa lewat Cloudflare/proxy.
    """

    meta = request.META

    cf = meta.get('HTTP_CF_CONNECTING_IP', '').strip()

    if cf:
        return cf

    xff = meta.get('HTTP_X_FORWARDED_FOR', '')

    if xff:
        pertama = xff.split(',')[0].strip()

        if pertama:
            return pertama

    return meta.get('REMOTE_ADDR', '')


# =========================================================
# MENCARI USER (USERNAME / NIS / NIP)
# =========================================================

def _cari_user(username_input):
    """
    Cari user lewat username, lalu fallback ke NIS dan NIP.
    Mengembalikan None jika tidak ditemukan.
    """

    user = Users.objects.filter(
        username=username_input
    ).first()

    if user:
        return user

    siswa_obj = Siswa.objects.filter(
        nis=username_input
    ).first()

    if siswa_obj:
        return siswa_obj.users

    kesiswaan_obj = Kesiswaan.objects.filter(
        nip=username_input
    ).first()

    if kesiswaan_obj:
        return kesiswaan_obj.user

    return None


# =========================================================
# MEMBUAT KUNCI PERCOBAAN
# =========================================================

def _kunci_akun(user, username_input):
    """
    Kunci hitungan percobaan berdasarkan AKUN.

    - Akun ada     -> pakai user.id, sehingga username/NIS/NIP
                      berbagi hitungan yang sama.
    - Akun tak ada -> pakai input yang dinormalisasi, supaya perilaku
                      dan pesan error tetap sama (tidak membocorkan
                      apakah akun ada atau tidak).
    """

    if user is not None:
        mentah = f'user:{user.id}'
    else:
        mentah = f'unknown:{username_input.strip().lower()}'

    return hashlib.sha256(
        mentah.encode('utf-8')
    ).hexdigest()


def _kunci_ip(request):
    """
    Kunci hitungan percobaan berdasarkan IP klien
    (dipakai untuk batas longgar anti password spraying).
    """

    return hashlib.sha256(
        f'ip:{_ip_klien(request)}'.encode('utf-8')
    ).hexdigest()


# =========================================================
# FORMAT SISA WAKTU PENGUNCIAN
# =========================================================

def _format_sisa_waktu(selisih):

    total_menit = max(
        1,
        -(-int(selisih.total_seconds()) // 60)
    )

    jam, menit = divmod(total_menit, 60)

    if jam and menit:
        return f'{jam} jam {menit} menit'

    if jam:
        return f'{jam} jam'

    return f'{menit} menit'


# =========================================================
# SIMPAN INFO KUNCI KE SESSION (UNTUK BANNER)
# =========================================================

def _set_info_kunci(request, sisa):
    """
    Simpan info kunci ke session agar bisa ditampilkan
    di halaman login setelah redirect.
    Pastikan settings.py: TIME_ZONE = 'Asia/Jakarta', USE_TZ = True.
    """

    sampai = timezone.localtime(timezone.now() + sisa)

    request.session['kunci_detik'] = int(sisa.total_seconds())
    request.session['kunci_sampai'] = sampai.strftime('%H:%M')


# =========================================================
# MEMERIKSA APAKAH KUNCI SEDANG TERKUNCI
# =========================================================

def _sisa_kunci(kunci):
    """
    Mengembalikan sisa waktu penguncian.
    Jika tidak terkunci, mengembalikan None.
    """

    rec = LoginAttempt.objects.filter(
        kunci=kunci
    ).first()

    sekarang = timezone.now()

    if (
        rec
        and rec.terkunci_sampai
        and rec.terkunci_sampai > sekarang
    ):
        return rec.terkunci_sampai - sekarang

    return None


# =========================================================
# MENCATAT PERCOBAAN LOGIN GAGAL
# =========================================================

def _catat_gagal(kunci, maks=MAKS_PERCOBAAN_GAGAL):
    """
    Menambah jumlah percobaan login gagal.

    Return:
    Jumlah sisa percobaan.
    0 berarti kunci baru saja terkunci.
    """

    sekarang = timezone.now()

    with transaction.atomic():

        rec, _ = (
            LoginAttempt.objects
            .select_for_update()
            .get_or_create(kunci=kunci)
        )

        # Periksa apakah penguncian sebelumnya sudah habis.
        kunci_habis = (
            rec.terkunci_sampai
            and rec.terkunci_sampai <= sekarang
        )

        # Periksa apakah jendela hitungan sudah kedaluwarsa.
        kadaluarsa = (
            rec.terakhir_gagal is None
            or sekarang - rec.terakhir_gagal > JENDELA_HITUNG
        )

        if kunci_habis or kadaluarsa:

            rec.jumlah_gagal = 0
            rec.terkunci_sampai = None

        rec.jumlah_gagal += 1
        rec.terakhir_gagal = sekarang

        # Kunci jika mencapai batas maksimal.
        if rec.jumlah_gagal >= maks:

            rec.terkunci_sampai = sekarang + DURASI_KUNCI

        rec.save()

    return max(
        0,
        maks - rec.jumlah_gagal
    )


# =========================================================
# LOGIN VIEW
# =========================================================

def login_view(request):
    """
    Halaman login otomatis.
    Mendeteksi role:
    - siswa
    - kesiswaan
    - admin
    - super_admin

    Menggunakan pola Post/Redirect/Get (PRG)
    untuk mencegah pengiriman ulang form ketika refresh.
    """

    # -----------------------------------------------------
    # 1. JIKA SUDAH LOGIN, ARAHKAN KE DASHBOARD
    # -----------------------------------------------------

    if (
        request.method == 'GET'
        and request.session.get('user_id')
    ):
        return _redirect_by_role(
            request.session.get('role')
        )

    # -----------------------------------------------------
    # 2. PROSES LOGIN
    # -----------------------------------------------------

    if request.method == 'POST':

        username_input = request.POST.get(
            'username', ''
        ).strip()

        password_input = request.POST.get(
            'password', ''
        )

        # -------------------------------------------------
        # 3. CARI USER DULU, BARU TENTUKAN KUNCI
        # -------------------------------------------------

        user = _cari_user(username_input)

        kunci = _kunci_akun(user, username_input)
        kunci_ip = _kunci_ip(request)

        # -------------------------------------------------
        # 4. PERIKSA APAKAH AKUN / IP SEDANG TERKUNCI
        # -------------------------------------------------

        sisa = _sisa_kunci(kunci)

        if sisa is None:
            sisa = _sisa_kunci(kunci_ip)

        if sisa is not None:

            _set_info_kunci(request, sisa)

            messages.error(
                request,
                f'Terlalu banyak percobaan login yang gagal. '
                f'Coba lagi dalam {_format_sisa_waktu(sisa)}.'
            )

            return redirect('login')

        # -------------------------------------------------
        # 5. BERSIHKAN SESSION LAMA
        # -------------------------------------------------

        request.session.flush()

        # -------------------------------------------------
        # 6. VALIDASI USERNAME DAN PASSWORD
        # -------------------------------------------------

        if (
            user is None
            or not check_password(
                password_input,
                user.password
            )
        ):

            # Catat gagal SEKALI saja untuk akun dan IP
            sisa_akun = _catat_gagal(kunci)
            sisa_ip = _catat_gagal(kunci_ip, maks=MAKS_GAGAL_PER_IP)

            # Tampilkan yang paling kecil dari keduanya
            sisa_percobaan = min(sisa_akun, sisa_ip)

            logger.warning(
                'Login gagal: ip=%s xff=%r sisa_akun=%s sisa_ip=%s',
                _ip_klien(request),
                request.META.get(
                    'HTTP_X_FORWARDED_FOR', ''
                ),
                sisa_akun,
                sisa_ip,
            )

            if sisa_ip <= 5 and sisa_ip < sisa_akun:
                messages.warning(
                    request,
                    'Banyak percobaan login gagal dari jaringan ini. '
                    'Harap periksa kembali data login Anda.'
                )

            if sisa_percobaan == 0:

                _set_info_kunci(request, DURASI_KUNCI)

                messages.error(
                    request,
                    f'Terlalu banyak percobaan login yang gagal. '
                    f'Login dikunci selama '
                    f'{_format_sisa_waktu(DURASI_KUNCI)}.'
                )

            else:

                messages.error(
                    request,
                    f'Username / NIS / NIP atau password salah. '
                    f'Sisa percobaan: {sisa_percobaan}.'
                )

            # PENTING:
            # Redirect harus berada di luar if/else.
            # Agar semua login gagal tidak mengirim ulang POST.
            return redirect('login')
        # -------------------------------------------------
        # 7. LOGIN BERHASIL, HAPUS CATATAN GAGAL AKUN
        #    (hitungan IP dibiarkan kedaluwarsa sendiri)
        # -------------------------------------------------

        LoginAttempt.objects.filter(
            kunci=kunci
        ).delete()

        # -------------------------------------------------
        # 8. VALIDASI KEANGGOTAAN SEKOLAH
        # -------------------------------------------------

        siswa_nonaktif = (
            user.role == 'siswa'
            and Siswa.objects.filter(
                users=user,
                status='keluar'
            ).exists()
        )

        if (
            not user.anggota_sekolah_valid
            and not siswa_nonaktif
        ):

            logger.warning(
                'Login ditolak (NPSN tidak cocok): '
                'user_id=%s npsn=%r',
                user.id,
                user.npsn,
            )

            messages.error(
                request,
                'Akun ini tidak terafiliasi dengan SMKN 11 Bandung. '
                'Hubungi admin sekolah jika ini sebuah kesalahan.'
            )

            return redirect('login')

        # -------------------------------------------------
        # 9. CARI NAMA LENGKAP BERDASARKAN ROLE
        # -------------------------------------------------

        nama_tampil = user.username

        if user.role == 'siswa':

            profil = Siswa.objects.filter(
                users=user
            ).first()

            if profil and profil.nama:

                nama_tampil = profil.nama

        elif user.role in (
            'kesiswaan',
            'admin',
            'super_admin'
        ):

            profil = Kesiswaan.objects.filter(
                user=user
            ).first()

            if profil and profil.nama:

                nama_tampil = profil.nama

        # -------------------------------------------------
        # 10. SIMPAN IDENTITAS KE SESSION
        # -------------------------------------------------

        request.session['user_id'] = user.id
        request.session['username'] = user.username
        request.session['role'] = user.role
        request.session['nama'] = nama_tampil

        # -------------------------------------------------
        # 11. PENANGANAN SISWA NONAKTIF
        # -------------------------------------------------

        if siswa_nonaktif:

            messages.warning(
                request,
                f'Halo, {nama_tampil}. Akun Anda berstatus '
                f'siswa nonaktif, sehingga hanya bisa '
                f'mengakses QR Code dan halaman portofolio.'
            )

            return redirect('siswa_qr_code')

        # -------------------------------------------------
        # 12. LOGIN BERHASIL
        # -------------------------------------------------

        messages.success(
            request,
            f'Selamat datang, {nama_tampil}!'
        )

        # Redirect sesuai role asli di database.
        return _redirect_by_role(user.role)

    # -----------------------------------------------------
    # 13. TAMPILKAN HALAMAN LOGIN (GET)
    #     pop() agar info kunci hanya muncul sekali
    # -----------------------------------------------------

    return render(
        request,
        'eprestasi/login.html',
        {
            'kunci_detik': request.session.pop('kunci_detik', None),
            'kunci_sampai': request.session.pop('kunci_sampai', None),
        }
    )


# =========================================================
# LOGOUT VIEW
# =========================================================

def logout_view(request):

    request.session.flush()

    messages.success(
        request,
        'Anda telah keluar.'
    )

    return redirect('login')


# =========================================================
# REDIRECT BERDASARKAN ROLE
# =========================================================

def _redirect_by_role(role):

    if role in ('admin', 'super_admin'):

        return redirect('dashboard')

    if role == 'siswa':

        return redirect('siswa_dashboard')

    if role == 'kesiswaan':

        return redirect('kesiswaan_dashboard')

    return redirect('login')