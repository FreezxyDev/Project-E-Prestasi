"""
Utilitas pengajuan prestasi: pencatat riwayat verifikasi dan deteksi kemungkinan duplikat.
"""
from django.db.models import Q

from .models import Prestasi, RiwayatVerifikasi


def catat_riwayat(prestasi, aksi, pelaku='', role='', status_sebelum='', status_baru='', catatan=''):
    """Tambah satu baris jejak verifikasi (append-only; tidak pernah diubah/dihapus)."""
    return RiwayatVerifikasi.objects.create(
        prestasi=prestasi, aksi=aksi, pelaku=pelaku or '', role_pelaku=role or '',
        status_sebelum=status_sebelum or '', status_baru=status_baru or '', catatan=catatan or '',
    )


def cari_duplikat(prestasi):
    """
    Pengajuan lain yang MUNGKIN duplikat (hanya peringatan -- tidak menghapus apa pun):
    - siswa sama + nama kegiatan sama + tanggal sama, atau
    - nomor sertifikat sama (siapa pun pemiliknya).
    Pengajuan yang sudah ditolak tidak dihitung.
    """
    kondisi = Q(siswa=prestasi.siswa, nama_prestasi__iexact=prestasi.nama_prestasi,
                tanggal_prestasi=prestasi.tanggal_prestasi)
    if prestasi.nomor_sertifikat:
        kondisi |= Q(nomor_sertifikat__iexact=prestasi.nomor_sertifikat)
    return (
        Prestasi.objects.filter(kondisi).exclude(pk=prestasi.pk).exclude(status='ditolak')
        .select_related('siswa')
    )
