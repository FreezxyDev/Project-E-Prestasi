"""
Helper kecil yang dipakai bersama oleh admin_views, siswa_views, dan kesiswaan_views
(sebelumnya disalin-tempel di banyak file).
"""
from django.contrib import messages
from django.shortcuts import redirect
from django.utils.http import url_has_allowed_host_and_scheme

from .form_fields import kumpulkan_pesan_error
from .models import Users

PAGE_SIZE = 10


def build_sort_toggle(current_sort, columns):
    """
    Untuk setiap nama kolom di `columns`, tentukan value 'sort' berikutnya kalau header kolom
    di-klik lagi (asc <-> desc). Template cukup memakai `sort_toggle.nama_kolom`.
    """
    toggle = {}
    for col in columns:
        asc, desc = f'{col}_asc', f'{col}_desc'
        toggle[col] = desc if current_sort == asc else asc
    return toggle


def kembali_ke(request, default_nama_url, field='next'):
    """Kembali ke halaman asal (beserta filter/pagination-nya) kalau 'next' aman, selain itu ke `default_nama_url`."""
    tujuan = request.POST.get(field, '') or request.GET.get(field, '')
    if tujuan and url_has_allowed_host_and_scheme(tujuan, allowed_hosts={request.get_host()}):
        return redirect(tujuan)
    return redirect(default_nama_url)


def ringkas_daftar(daftar, maks=10):
    """['a','b',...] -> 'a, b, ... dan 3 lainnya' untuk pesan ringkas."""
    teks = ', '.join(daftar[:maks])
    return teks + (f' dan {len(daftar) - maks} lainnya' if len(daftar) > maks else '')


def pesan_error_form(request, form):
    """Tampilkan semua error form sebagai messages.error (satu pesan per error)."""
    for pesan in kumpulkan_pesan_error(form):
        messages.error(request, pesan)


def pengguna_saat_ini(request):
    """Objek Users dari sesi login, atau None."""
    user_id = request.session.get('user_id')
    return Users.objects.filter(id=user_id).first() if user_id else None
