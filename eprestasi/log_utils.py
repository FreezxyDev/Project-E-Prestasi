"""
Helper terpusat untuk mencatat Log Aktivitas.
Dipakai oleh views.py, kesiswaan_views.py, import_views.py, kelas_views.py,
dan siswa_prestasi_views.py supaya format pencatatan seragam di seluruh
sistem (dipakai halaman Log Aktivitas & widget "Aktivitas Terbaru" Dashboard).
"""
from .models import LogAktivitas


def catat_aktivitas(request, aksi, judul, deskripsi='', modul='', status_log='berhasil'):
    """
    Simpan satu baris jejak aktivitas.
    - aksi       : salah satu LogAktivitas.AKSI_CHOICES.
    - judul      : teks aktivitas singkat, tampil di kolom "Aktivitas".
    - deskripsi  : detail tambahan, tampil di kolom "Detail".
    - modul      : salah satu LogAktivitas.MODUL_CHOICES (siswa/kesiswaan/dst).
    - status_log : 'berhasil' (default) atau 'gagal'.
    """
    LogAktivitas.objects.create(
        aksi=aksi,
        judul=judul,
        deskripsi=deskripsi,
        actor=request.session.get('username', ''),
        role_actor=request.session.get('role', ''),
        modul=modul,
        status_log=status_log,
    )