import hashlib
import logging
from datetime import timedelta

from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth.hashers import check_password
from django.db import transaction
from django.utils import timezone

from .models import Users, Siswa, Kesiswaan, LoginAttempt

logger = logging.getLogger(__name__)

# ---- Pembatasan percobaan login ----
MAKS_PERCOBAAN_GAGAL = 5                 # gagal sebanyak ini -> dikunci
DURASI_KUNCI = timedelta(hours=3)        # lama penguncian
# Hitungan gagal direset kalau percobaan gagal terakhir sudah lebih lama dari ini,
# supaya salah ketik yang berjauhan waktunya tidak menumpuk jadi kunci.
JENDELA_HITUNG = timedelta(hours=3)


def _ip_klien(request):
    """
    IP asli klien. Urutan: CF-Connecting-IP (Cloudflare) -> entri PERTAMA
    X-Forwarded-For (klien asli; proxy menambah IP-nya di belakang) -> REMOTE_ADDR.
    Entri TERAKHIR sengaja tidak dipakai: dengan beberapa proxy itu adalah IP proxy
    internal yang bisa berganti tiap request, sehingga hitungan gagal tidak menumpuk.
    Catatan: header ini bisa dipalsukan kalau server tidak berada di belakang proxy
    yang menimpanya, jadi sesuaikan dengan susunan hosting kalau perlu.
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


def _kunci_percobaan(request):
    """
    Kunci hitungan = IP klien SAJA (bukan akun yang diketik). Jadi semua percobaan
    gagal dari satu IP dihitung bersama, siapa pun/akun apa pun yang dicoba.
    Konsekuensi: perangkat yang berbagi satu IP publik (mis. wifi sekolah) berbagi
    jatah percobaan yang sama.
    """
    return hashlib.sha256(_ip_klien(request).encode('utf-8')).hexdigest()


def _format_sisa_waktu(selisih):
    total_menit = max(1, -(-int(selisih.total_seconds()) // 60))  # dibulatkan ke atas
    jam, menit = divmod(total_menit, 60)
    if jam and menit:
        return f'{jam} jam {menit} menit'
    if jam:
        return f'{jam} jam'
    return f'{menit} menit'


def _sisa_kunci(kunci):
    """Return sisa waktu kunci (timedelta) kalau sedang terkunci, selain itu None."""
    rec = LoginAttempt.objects.filter(kunci=kunci).first()
    if rec and rec.terkunci_sampai and rec.terkunci_sampai > timezone.now():
        return rec.terkunci_sampai - timezone.now()
    return None


def _catat_gagal(kunci):
    """Tambah hitungan gagal. Return jumlah sisa percobaan (0 kalau baru saja terkunci)."""
    sekarang = timezone.now()
    with transaction.atomic():
        rec, _ = LoginAttempt.objects.select_for_update().get_or_create(kunci=kunci)
        # Kunci lama sudah habis, atau percobaan terakhir sudah lama -> mulai dari nol.
        kunci_habis = rec.terkunci_sampai and rec.terkunci_sampai <= sekarang
        kadaluarsa = sekarang - rec.terakhir_gagal > JENDELA_HITUNG
        if kunci_habis or kadaluarsa:
            rec.jumlah_gagal = 0
            rec.terkunci_sampai = None

        rec.jumlah_gagal += 1
        rec.terakhir_gagal = sekarang
        if rec.jumlah_gagal >= MAKS_PERCOBAAN_GAGAL:
            rec.terkunci_sampai = sekarang + DURASI_KUNCI
        rec.save()
    return max(0, MAKS_PERCOBAAN_GAGAL - rec.jumlah_gagal)


def login_view(request):
    """
    Halaman login otomatis (1 field): Otomatis mendeteksi role (siswa, kesiswaan, admin).
    """
    # 1. Jika user sudah login DAN cuma buka halaman login (GET),
    #    langsung lempar ke dashboard masing-masing.
    #    PENTING: cek ini HANYA untuk GET. Kalau dibiarkan jalan juga saat POST,
    #    submit form login baru (misal login sebagai super admin) akan langsung
    #    di-redirect pakai role SESSION LAMA (misal siswa) tanpa sempat
    #    memvalidasi username/password yang baru diinput sama sekali.
    if request.method == 'GET' and request.session.get('user_id'):
        return _redirect_by_role(request.session.get('role'))

    if request.method == 'POST':
        username_input = request.POST.get('username', '').strip()
        password_input = request.POST.get('password', '')
        kunci = _kunci_percobaan(request)

        # 0. Sedang dikunci? Tolak SEBELUM memeriksa password, jadi password yang
        #    benar pun tidak diterima sampai kuncinya habis.
        sisa = _sisa_kunci(kunci)
        if sisa is not None:
            messages.error(
                request,
                f'Terlalu banyak percobaan login yang gagal. '
                f'Coba lagi dalam {_format_sisa_waktu(sisa)}.'
            )
            return render(request, 'eprestasi/login.html')

        # Pastikan tidak ada sisa session lama yang nyangkut sebelum login baru diproses.
        request.session.flush()

        # 2. Cari user di DB berdasarkan username/NIS/NIP tanpa memfilter role
        user = Users.objects.filter(username=username_input).first()

        # Fallback: Jika tidak ketemu di Users, cari lewat NIS (Siswa) / NIP (Kesiswaan)
        if not user:
            siswa_obj = Siswa.objects.filter(nis=username_input).first()
            if siswa_obj:
                user = siswa_obj.users
            else:
                kesiswaan_obj = Kesiswaan.objects.filter(nip=username_input).first()
                if kesiswaan_obj:
                    user = kesiswaan_obj.user

        # 3. Validasi Keberadaan User & Password
        if user is None or not check_password(password_input, user.password):
            sisa_percobaan = _catat_gagal(kunci)
            # Log untuk memeriksa apakah IP terbaca stabil (lihat log server).
            logger.warning(
                'Login gagal: ip=%s xff=%r sisa_percobaan=%s',
                _ip_klien(request), request.META.get('HTTP_X_FORWARDED_FOR', ''), sisa_percobaan,
            )
            if sisa_percobaan == 0:
                messages.error(
                    request,
                    f'Terlalu banyak percobaan login yang gagal. '
                    f'Login dikunci selama {_format_sisa_waktu(DURASI_KUNCI)}.'
                )
            else:
                messages.error(
                    request,
                    f'Username / NIS / NIP atau password salah. '
                    f'Sisa percobaan: {sisa_percobaan}.'
                )
            return render(request, 'eprestasi/login.html')

        # Login berhasil -> hapus catatan gagal untuk kunci ini.
        LoginAttempt.objects.filter(kunci=kunci).delete()

        # =========================================================
        # CARI NAMA LENGKAP DARI TABEL PROFIL BERDASARKAN ROLE
        # =========================================================
        nama_tampil = user.username  # Default fallback jika profil belum diisi

        if user.role == 'siswa':
            profil = Siswa.objects.filter(users=user).first()
            if profil and profil.nama:
                nama_tampil = profil.nama

        elif user.role in ('kesiswaan', 'admin', 'super_admin'):
            profil = Kesiswaan.objects.filter(user=user).first()
            if profil and profil.nama:
                nama_tampil = profil.nama

        # =========================================================
        # SIMPAN IDENTITAS KE SESSION
        # =========================================================
        request.session['user_id'] = user.id
        request.session['username'] = user.username
        request.session['role'] = user.role
        request.session['nama'] = nama_tampil

        messages.success(request, f'Selamat datang, {nama_tampil}!')
        
        # 4. Redirect otomatis ke dashboard sesuai role asli di DB
        return _redirect_by_role(user.role)

    return render(request, 'eprestasi/login.html')


def logout_view(request):
    request.session.flush()  # Hapus semua data session
    messages.success(request, 'Anda telah keluar.')
    return redirect('login')


def _redirect_by_role(role):
    if role in ('admin', 'super_admin'):
        return redirect('dashboard')
    if role == 'siswa':
        return redirect('siswa_dashboard')
    if role == 'kesiswaan':
        return redirect('kesiswaan_dashboard')
    return redirect('login')