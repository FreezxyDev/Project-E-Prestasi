"""
Siswa Keluar / Dikeluarkan
==========================
Admin menandai siswa yang keluar (pindah/mengundurkan diri) atau dikeluarkan dari
SMKN 11 Bandung. Efeknya:
  - Siswa.status        -> 'keluar' (+ jenis, tanggal, keterangan)
  - Users.npsn          -> dikosongkan (akun tidak lagi terafiliasi dengan SMKN 11 Bandung)
  - Siswa NONAKTIF tetap bisa login, tapi hanya ke halaman QR Code (lihat decorators.py);
    upload prestasi, riwayat, profil, dll diblokir.
  - Prestasi, sertifikat, dokumentasi, dan portofolio publik TIDAK dihapus.
Admin bisa memulihkan siswa (mis. salah input / siswa kembali) -> NPSN diisi lagi.
"""
from datetime import date

from django.contrib import messages
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.views.decorators.http import require_POST

from .decorators import role_required
from .log_utils import catat_aktivitas
from .models import Siswa, NPSN_SMKN_11_BANDUNG

LABEL_JENIS = dict(Siswa.JENIS_KELUAR_CHOICES)


def _kembali(request):
    return redirect('siswa_list')


@role_required('admin', 'super_admin')
@require_POST
def keluarkan_siswa(request, siswa_id):
    siswa = get_object_or_404(Siswa.objects.select_related('users'), id=siswa_id)

    if siswa.status == 'keluar':
        messages.warning(request, f'{siswa.nama or siswa.nis} sudah berstatus keluar.')
        return _kembali(request)
    if siswa.status == 'alumni':
        messages.error(request, 'Alumni tidak bisa dikeluarkan. Alumni adalah siswa yang sudah lulus.')
        return _kembali(request)

    jenis = request.POST.get('jenis_keluar', '')
    if jenis not in LABEL_JENIS:
        messages.error(request, 'Pilih jenis: keluar/mengundurkan diri atau dikeluarkan.')
        return _kembali(request)

    tanggal = timezone.localdate()
    tanggal_input = request.POST.get('tanggal_keluar', '').strip()
    if tanggal_input:
        try:
            tanggal = date.fromisoformat(tanggal_input)
        except ValueError:
            messages.error(request, 'Format tanggal tidak valid.')
            return _kembali(request)

    keterangan = request.POST.get('keterangan_keluar', '').strip()
    status_lama = siswa.status

    with transaction.atomic():
        siswa.status = 'keluar'
        siswa.jenis_keluar = jenis
        siswa.tanggal_keluar = tanggal
        siswa.keterangan_keluar = keterangan
        siswa.save()

        siswa.users.npsn = ''          # cabut afiliasi -> login ditolak
        siswa.users.save(update_fields=['npsn', 'updated_at'])

    catat_aktivitas(
        request, 'siswa_keluar',
        'Admin menandai siswa keluar',
        f'Siswa "{siswa.nama}" (NIS {siswa.nis}) ditandai {LABEL_JENIS[jenis]} per {tanggal:%d-%m-%Y} '
        f'(status sebelumnya: {status_lama}). NPSN akun dicabut; akun menjadi siswa nonaktif.'
        + (f' Keterangan: {keterangan}' if keterangan else ''),
        modul='siswa',
    )
    messages.success(
        request,
        f'{siswa.nama or siswa.nis} ditandai {LABEL_JENIS[jenis].lower()} dan kini menjadi siswa nonaktif: '
        f'masih bisa login hanya untuk melihat portofolio & QR Code, tidak bisa upload prestasi.'
    )
    return _kembali(request)


@role_required('admin', 'super_admin')
@require_POST
def pulihkan_siswa(request, siswa_id):
    siswa = get_object_or_404(Siswa.objects.select_related('users'), id=siswa_id)

    if siswa.status != 'keluar':
        messages.warning(request, 'Siswa ini tidak berstatus keluar.')
        return _kembali(request)

    with transaction.atomic():
        siswa.status = 'aktif'
        siswa.jenis_keluar = None
        siswa.tanggal_keluar = None
        siswa.keterangan_keluar = ''
        siswa.save()

        siswa.users.npsn = NPSN_SMKN_11_BANDUNG   # afiliasi dipulihkan
        siswa.users.save(update_fields=['npsn', 'updated_at'])

    catat_aktivitas(
        request, 'siswa_dipulihkan',
        'Admin memulihkan siswa',
        f'Siswa "{siswa.nama}" (NIS {siswa.nis}) dipulihkan ke status aktif. NPSN akun diisi kembali.',
        modul='siswa',
    )
    messages.success(request, f'{siswa.nama or siswa.nis} dipulihkan dan kembali menjadi siswa aktif dengan akses penuh.')
    return _kembali(request)
