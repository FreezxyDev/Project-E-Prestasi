"""
Fitur Lupa Password.

Alur siswa (tanpa login):
  1. /lupa-password/            -> isi NIS / username
  2. /lupa-password/metode/     -> pilih cara reset
        * profil BELUM lengkap  -> hanya bisa kirim permintaan ke admin
        * profil lengkap        -> OTP ke email, OTP ke no HP, atau permintaan ke admin
  3. /lupa-password/verifikasi/ -> isi kode OTP (6 digit, berlaku 10 menit, sekali pakai,
                                   bisa kirim ulang)
  4. /lupa-password/baru/       -> isi password baru

Admin: menu "Permintaan Reset Password" -> reset (password sementara acak) atau tolak.
"""
import hashlib
from datetime import timedelta

from django.contrib import messages
from django.db import transaction
from django.contrib.auth.hashers import make_password
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_POST

from .auth_views import _ip_klien, _catat_gagal, _sisa_kunci, _format_sisa_waktu
from .decorators import role_required
from .forms import LupaPasswordBaruForm
from .import_views import _buat_password_acak
from .log_utils import catat_aktivitas
from .models import (
    Users, Siswa, LogAktivitas, OtpResetPassword, PermintaanResetPassword,
)
from . import otp_utils

# Kunci session
S_USER = 'lp_user_id'
S_OTP = 'lp_otp_id'
S_VERIFIED_UNTIL = 'lp_verified_until'   # epoch detik; batas waktu mengisi password baru
S_PASSWORD_SEMENTARA = 'lp_password_sementara'  # khusus admin, ditampilkan sekali

MASA_FORM_PASSWORD_BARU = timedelta(minutes=10)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------
def _kunci_pencarian(request):
    """Pembatas percobaan cari akun (anti tebak-tebak NIS), terpisah dari kunci login."""
    return hashlib.sha256(f'lupa-password:{_ip_klien(request)}'.encode('utf-8')).hexdigest()


def _bersihkan_session(request):
    for k in (S_USER, S_OTP, S_VERIFIED_UNTIL):
        request.session.pop(k, None)


def _cari_siswa(identitas):
    """Cari siswa lewat username akun atau NIS (sama seperti halaman login)."""
    user = Users.objects.filter(username=identitas, role='siswa').first()
    if user:
        siswa = Siswa.objects.filter(users=user).first()
    else:
        siswa = Siswa.objects.select_related('users').filter(nis=identitas).first()
        user = siswa.users if siswa else None
    if not siswa or not user or user.role != 'siswa':
        return None, None
    return user, siswa


def _akun_boleh_reset(user, siswa):
    """Siswa yang sudah keluar tetap boleh (mereka masih bisa login ke QR Code)."""
    return user.anggota_sekolah_valid or siswa.status == 'keluar'


def _muat_sesi(request):
    """Ambil (user, siswa) dari session; None kalau sesi lupa-password tidak ada."""
    user_id = request.session.get(S_USER)
    if not user_id:
        return None, None
    user = Users.objects.filter(id=user_id, role='siswa').first()
    siswa = Siswa.objects.filter(users=user).first() if user else None
    if not user or not siswa:
        _bersihkan_session(request)
        return None, None
    return user, siswa


def _kontak_siswa(siswa):
    return {
        'email': (siswa.email or '').strip(),
        'hp': (siswa.no_hp or '').strip(),
    }


def _detik_sisa(waktu_akhir):
    return max(0, int((waktu_akhir - timezone.now()).total_seconds()))


def _kirim_otp(user, siswa, kanal):
    """
    Buat OTP baru (yang lama dihanguskan) lalu kirim.
    Return (otp, pesan_error). otp=None kalau gagal.
    """
    kontak = _kontak_siswa(siswa)
    tujuan = kontak['email'] if kanal == 'email' else kontak['hp']
    if not tujuan:
        return None, 'Kontak untuk metode ini belum tersedia di profil kamu.'

    sekarang = timezone.now()
    with transaction.atomic():
        Users.objects.select_for_update().get(pk=user.pk)  # kunci supaya tidak balapan

        terakhir = OtpResetPassword.objects.filter(user=user).order_by('-dibuat_pada').first()
        if terakhir:
            sisa = otp_utils.JEDA_KIRIM_ULANG - (sekarang - terakhir.dibuat_pada)
            if sisa.total_seconds() > 0:
                return None, f'Tunggu {int(sisa.total_seconds()) + 1} detik sebelum meminta kode lagi.'

        sejam = OtpResetPassword.objects.filter(
            user=user, dibuat_pada__gte=sekarang - timedelta(hours=1)
        ).count()
        if sejam >= otp_utils.MAKS_KIRIM_PER_JAM:
            return None, 'Terlalu banyak permintaan kode OTP. Coba lagi dalam 1 jam, atau minta reset lewat admin.'

        OtpResetPassword.objects.filter(user=user, terpakai=False).update(terpakai=True)

        kode = otp_utils.buat_kode()
        otp = OtpResetPassword.objects.create(
            user=user, kanal=kanal, tujuan=tujuan,
            kode_hash=otp_utils.hash_kode(user.id, kode),
            dibuat_pada=sekarang,
            kedaluwarsa_pada=sekarang + otp_utils.MASA_BERLAKU_OTP,
        )

    nama = siswa.nama or siswa.nis
    berhasil = (
        otp_utils.kirim_otp_email(tujuan, kode, nama) if kanal == 'email'
        else otp_utils.kirim_otp_hp(tujuan, kode, nama)
    )
    if not berhasil:
        otp.delete()  # gagal terkirim -> jangan dihitung sebagai pengiriman
        return None, 'Kode OTP gagal dikirim. Coba lagi sebentar lagi atau minta reset lewat admin.'
    return otp, None


# ---------------------------------------------------------------------------
# 1. Cari akun
# ---------------------------------------------------------------------------
def lupa_password(request):
    if request.method == 'POST':
        kunci = _kunci_pencarian(request)
        sisa = _sisa_kunci(kunci)
        if sisa is not None:
            messages.error(
                request,
                f'Terlalu banyak percobaan. Coba lagi dalam {_format_sisa_waktu(sisa)}.'
            )
            return render(request, 'eprestasi/lupa_password/cari_akun.html')

        identitas = request.POST.get('identitas', '').strip()
        user, siswa = _cari_siswa(identitas) if identitas else (None, None)

        if not user:
            _catat_gagal(kunci)
            messages.error(
                request,
                'Akun siswa dengan NIS / username tersebut tidak ditemukan. '
                'Untuk akun kesiswaan atau admin, hubungi administrator.'
            )
            return render(request, 'eprestasi/lupa_password/cari_akun.html', {'identitas': identitas})

        if not _akun_boleh_reset(user, siswa):
            messages.error(
                request,
                'Akun ini tidak terafiliasi dengan SMKN 11 Bandung. Hubungi admin sekolah.'
            )
            return render(request, 'eprestasi/lupa_password/cari_akun.html', {'identitas': identitas})

        _bersihkan_session(request)
        request.session[S_USER] = user.id
        return redirect('lupa_password_metode')

    return render(request, 'eprestasi/lupa_password/cari_akun.html')


# ---------------------------------------------------------------------------
# 2. Pilih metode
# ---------------------------------------------------------------------------
def lupa_password_metode(request):
    user, siswa = _muat_sesi(request)
    if not user:
        return redirect('lupa_password')

    lengkap = siswa.profil_lengkap
    kontak = _kontak_siswa(siswa)
    pending = PermintaanResetPassword.objects.filter(siswa=siswa, status='pending').first()

    if request.method == 'POST':
        aksi = request.POST.get('aksi')

        if aksi == 'admin':
            if not pending:
                pending = PermintaanResetPassword.objects.create(
                    siswa=siswa,
                    alasan='pilih_admin' if lengkap else 'profil_belum_lengkap',
                )
            _bersihkan_session(request)
            return render(request, 'eprestasi/lupa_password/permintaan_terkirim.html', {
                'siswa': siswa, 'permintaan': pending,
            })

        if aksi in ('email', 'hp') and lengkap:
            otp, error = _kirim_otp(user, siswa, aksi)
            if error:
                messages.error(request, error)
            else:
                request.session[S_OTP] = otp.id
                messages.success(
                    request,
                    f'Kode OTP dikirim ke {"email" if aksi == "email" else "nomor HP"} kamu.'
                )
                return redirect('lupa_password_verifikasi')
        elif aksi in ('email', 'hp'):
            messages.error(request, 'Profil kamu belum lengkap, jadi OTP belum bisa dipakai.')

    return render(request, 'eprestasi/lupa_password/pilih_metode.html', {
        'siswa': siswa,
        'lengkap': lengkap,
        'email_samar': otp_utils.samarkan_email(kontak['email']) if kontak['email'] else '',
        'hp_samar': otp_utils.samarkan_hp(kontak['hp']) if kontak['hp'] else '',
        'pending': pending,
    })


# ---------------------------------------------------------------------------
# 3. Verifikasi OTP (+ kirim ulang)
# ---------------------------------------------------------------------------
def lupa_password_verifikasi(request):
    user, siswa = _muat_sesi(request)
    if not user:
        return redirect('lupa_password')

    otp = OtpResetPassword.objects.filter(id=request.session.get(S_OTP), user=user).first()
    if not otp:
        return redirect('lupa_password_metode')

    if request.method == 'POST':
        aksi = request.POST.get('aksi')

        # ---- Kirim ulang ----
        if aksi == 'kirim_ulang':
            baru, error = _kirim_otp(user, siswa, otp.kanal)
            if error:
                messages.error(request, error)
            else:
                request.session[S_OTP] = baru.id
                messages.success(request, 'Kode OTP baru sudah dikirim. Kode sebelumnya tidak berlaku lagi.')
            return redirect('lupa_password_verifikasi')

        # ---- Verifikasi ----
        kode = ''.join(ch for ch in request.POST.get('kode', '') if ch.isdigit())
        with transaction.atomic():
            otp = OtpResetPassword.objects.select_for_update().get(pk=otp.pk)

            if otp.terpakai:
                messages.error(request, 'Kode ini sudah tidak berlaku. Silakan kirim ulang kode OTP.')
            elif otp.kedaluwarsa_pada <= timezone.now():
                messages.error(request, 'Kode OTP sudah kedaluwarsa (berlaku 10 menit). Silakan kirim ulang.')
            elif len(kode) != otp_utils.PANJANG_OTP or not otp_utils.cocok(user.id, kode, otp.kode_hash):
                otp.percobaan_salah += 1
                if otp.percobaan_salah >= otp_utils.MAKS_SALAH_PER_OTP:
                    otp.terpakai = True  # hangus
                    messages.error(request, 'Terlalu banyak salah memasukkan kode. Silakan kirim ulang kode OTP.')
                else:
                    sisa = otp_utils.MAKS_SALAH_PER_OTP - otp.percobaan_salah
                    messages.error(request, f'Kode OTP salah. Sisa percobaan: {sisa}.')
                otp.save(update_fields=['percobaan_salah', 'terpakai'])
            else:
                # Benar -> langsung dihanguskan (sekali pakai).
                otp.terpakai = True
                otp.save(update_fields=['terpakai'])
                request.session[S_VERIFIED_UNTIL] = (timezone.now() + MASA_FORM_PASSWORD_BARU).timestamp()
                request.session.pop(S_OTP, None)
                return redirect('lupa_password_baru')

    sekarang = timezone.now()
    jeda_akhir = otp.dibuat_pada + otp_utils.JEDA_KIRIM_ULANG
    tujuan_samar = (
        otp_utils.samarkan_email(otp.tujuan) if otp.kanal == 'email'
        else otp_utils.samarkan_hp(otp.tujuan)
    )
    return render(request, 'eprestasi/lupa_password/verifikasi_otp.html', {
        'siswa': siswa,
        'otp': otp,
        'tujuan_samar': tujuan_samar,
        'sisa_jeda': _detik_sisa(jeda_akhir) if jeda_akhir > sekarang else 0,
        'sisa_berlaku': 0 if (otp.terpakai or otp.kedaluwarsa_pada <= sekarang) else _detik_sisa(otp.kedaluwarsa_pada),
        'masa_berlaku_menit': int(otp_utils.MASA_BERLAKU_OTP.total_seconds() // 60),
    })


# ---------------------------------------------------------------------------
# 4. Password baru
# ---------------------------------------------------------------------------
def lupa_password_baru(request):
    user, siswa = _muat_sesi(request)
    if not user:
        return redirect('lupa_password')

    batas = request.session.get(S_VERIFIED_UNTIL)
    if not batas or timezone.now().timestamp() > batas:
        _bersihkan_session(request)
        messages.error(request, 'Sesi reset password sudah habis. Silakan ulangi dari awal.')
        return redirect('lupa_password')

    if request.method == 'POST':
        form = LupaPasswordBaruForm(request.POST, user=user, siswa=siswa)
        if form.is_valid():
            user.password = make_password(form.cleaned_data['password_baru'])
            user.save(update_fields=['password', 'updated_at'])

            # Semua OTP lain hangus; permintaan ke admin yang masih menunggu dianggap selesai.
            OtpResetPassword.objects.filter(user=user, terpakai=False).update(terpakai=True)
            PermintaanResetPassword.objects.filter(siswa=siswa, status='pending').update(
                status='selesai', diproses_pada=timezone.now(),
                diproses_oleh=user.username, catatan='Direset sendiri oleh siswa lewat OTP.',
            )
            LogAktivitas.objects.create(
                aksi='password_direset',
                judul='Siswa mereset password lewat OTP',
                deskripsi=f'Siswa "{siswa.nama or siswa.nis}" (NIS {siswa.nis}) mereset password '
                          f'lewat OTP.',
                actor=user.username, role_actor='siswa', modul='siswa',
            )
            _bersihkan_session(request)
            messages.success(request, 'Password berhasil diubah. Silakan login dengan password baru.')
            return redirect('login')
    else:
        form = LupaPasswordBaruForm(user=user, siswa=siswa)

    return render(request, 'eprestasi/lupa_password/password_baru.html', {'form': form, 'siswa': siswa})


# ===========================================================================
# ADMIN: kelola permintaan reset password
# ===========================================================================
FILTER_STATUS = ('pending', 'selesai', 'ditolak')
PERMINTAAN_PER_HALAMAN = 25


@role_required('admin', 'super_admin')
def permintaan_reset_list(request):
    status = request.GET.get('status', 'pending')
    if status not in FILTER_STATUS:
        status = 'pending'

    qs = (PermintaanResetPassword.objects.filter(status=status)
          .select_related('siswa', 'siswa__users')[:PERMINTAAN_PER_HALAMAN])
    hitung = {s: PermintaanResetPassword.objects.filter(status=s).count() for s in FILTER_STATUS}

    return render(request, 'eprestasi/permintaan_reset/list.html', {
        'active_menu': 'permintaan_reset',
        'daftar': list(qs),
        'status': status,
        'hitung': hitung,
        'password_sementara': request.session.pop(S_PASSWORD_SEMENTARA, None),
    })


@role_required('admin', 'super_admin')
@require_POST
def permintaan_reset_proses(request, permintaan_id):
    """Reset password siswa ke password sementara acak (ditampilkan SEKALI ke admin)."""
    with transaction.atomic():
        permintaan = get_object_or_404(
            PermintaanResetPassword.objects.select_for_update().select_related('siswa', 'siswa__users'),
            pk=permintaan_id,
        )
        if permintaan.status != 'pending':
            messages.warning(request, 'Permintaan ini sudah diproses sebelumnya.')
            return redirect('permintaan_reset_list')

        siswa = permintaan.siswa
        password = _buat_password_acak(8)
        user = siswa.users
        user.password = make_password(password)
        user.save(update_fields=['password', 'updated_at'])

        permintaan.status = 'selesai'
        permintaan.diproses_pada = timezone.now()
        permintaan.diproses_oleh = request.session.get('username', '')
        permintaan.save(update_fields=['status', 'diproses_pada', 'diproses_oleh'])

    catat_aktivitas(
        request, 'password_direset', 'Admin mereset password siswa (permintaan siswa)',
        f'Password siswa "{siswa.nama or siswa.nis}" (NIS {siswa.nis}) direset atas permintaan siswa.',
        modul='siswa',
    )
    request.session[S_PASSWORD_SEMENTARA] = {
        'nis': siswa.nis, 'nama': siswa.nama or '-', 'password': password,
    }
    messages.success(request, f'Password siswa NIS {siswa.nis} berhasil direset.')
    return redirect('permintaan_reset_list')


@role_required('admin', 'super_admin')
@require_POST
def permintaan_reset_tolak(request, permintaan_id):
    permintaan = get_object_or_404(PermintaanResetPassword.objects.select_related('siswa'), pk=permintaan_id)
    if permintaan.status != 'pending':
        messages.warning(request, 'Permintaan ini sudah diproses sebelumnya.')
        return redirect('permintaan_reset_list')

    permintaan.status = 'ditolak'
    permintaan.diproses_pada = timezone.now()
    permintaan.diproses_oleh = request.session.get('username', '')
    permintaan.catatan = request.POST.get('catatan', '').strip()[:255]
    permintaan.save(update_fields=['status', 'diproses_pada', 'diproses_oleh', 'catatan'])

    catat_aktivitas(
        request, 'password_direset', 'Admin menolak permintaan reset password',
        f'Permintaan reset password siswa NIS {permintaan.siswa.nis} ditolak.',
        modul='siswa',
    )
    messages.success(request, f'Permintaan reset password NIS {permintaan.siswa.nis} ditolak.')
    return redirect('permintaan_reset_list')
