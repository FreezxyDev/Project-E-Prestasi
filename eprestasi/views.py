"""
View HALAMAN PUBLIK (tanpa login): landing page dan API pencarian siswa.

Pembagian modul view:
- admin_views.py     -> semua kebutuhan admin / super admin
- siswa_views.py     -> portal siswa, pengajuan prestasi, lupa password, portofolio publik
- kesiswaan_views.py -> portal kesiswaan (verifikasi prestasi, laporan, dst.)
- auth_views.py      -> login / logout
"""
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import render
from django.urls import reverse

from . import validasi as v
from .models import Siswa


def landing_page(request):
    """Halaman landing page (awal) aplikasi e-prestasi."""
    return render(request, 'eprestasi/landing_page.html')


def cari_siswa_api(request):
    """
    API PUBLIK untuk section "Cari Siswa" di landing page (tanpa login).
    Mencari akun siswa sungguhan berdasarkan NIS atau nama, lalu mengembalikan
    link ke halaman portofolio publik mereka.

    Sengaja hanya mengembalikan data yang memang sudah tampil di portofolio
    publik (NIS, nama, kelas, jurusan, jumlah prestasi terverifikasi) -- tidak ada
    email/no HP/alamat. Query minimal 3 karakter dan hasil dibatasi, supaya
    daftar siswa tidak bisa diambil sekaligus lewat pencarian satu huruf.
    """
    q = v.rapikan_spasi(request.GET.get('q', ''))[:50]   # sanitasi + batas panjang
    if len(q) < 3:
        return JsonResponse({'results': [], 'terlalu_pendek': True})

    siswa_qs = (
        Siswa.objects
        .filter(status__in=['aktif', 'alumni'])
        .filter(Q(nis__icontains=q) | Q(nama__icontains=q))
        .annotate(total_prestasi=Count('prestasi', filter=Q(prestasi__status='diterima')))
        .order_by('nama', 'nis')[:12]
    )
    results = [
        {
            'nis': s.nis,
            'nama': s.nama or s.nis,
            'kelas': s.kelas or '-',
            'jurusan': s.jurusan or '-',
            'alumni': s.status == 'alumni',
            'prestasi': s.total_prestasi,
            'url': reverse('portofolio_publik', args=[s.nis]),
        }
        for s in siswa_qs
    ]
    return JsonResponse({'results': results, 'terlalu_pendek': False})
