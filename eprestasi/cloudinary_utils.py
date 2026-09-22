"""
Helper kecil untuk benar-benar menghapus file dari Cloudinary (bukan cuma
menghapus baris di database). Dipakai saat kesiswaan menolak prestasi, atau
mengembalikan prestasi untuk "perbaikan file" -- di kedua kasus itu file
sertifikat lama harus hilang dari penyimpanan, bukan cuma dari tampilan.
"""
import logging

import cloudinary.uploader

logger = logging.getLogger(__name__)


def hapus_file_cloudinary(file_field):
    """
    Hapus 1 file Cloudinary. Upload aslinya pakai resource_type='auto', dan
    Cloudinary sendiri yang memutuskan itu ke-detect sebagai 'image', 'raw'
    (dokumen non-gambar seperti PDF), atau 'video' -- info itu tidak disimpan
    balik ke database kita, jadi di sini kita coba ketiganya; begitu salah
    satu berhasil ('result': 'ok'), berhenti.

    Sengaja tidak melempar exception kalau gagal -- proses verifikasi
    (ganti status prestasi) tidak boleh gagal total hanya karena Cloudinary
    lagi bermasalah/di luar jangkauan. Kegagalan cukup dicatat ke log.
    """
    if not file_field:
        return False

    public_id = getattr(file_field, 'public_id', None)
    if not public_id:
        return False

    for resource_type in ('image', 'raw', 'video'):
        try:
            hasil = cloudinary.uploader.destroy(
                public_id, resource_type=resource_type, invalidate=True
            )
            if hasil.get('result') == 'ok':
                return True
        except Exception:
            logger.exception(
                'Gagal menghapus file Cloudinary public_id=%s (resource_type=%s)',
                public_id, resource_type,
            )
            continue

    return False


def hapus_sertifikat_prestasi(prestasi):
    """
    Hapus SEMUA file sertifikat milik satu prestasi -- dari Cloudinary
    sekaligus baris Sertifikat-nya di database. Dipakai saat prestasi
    ditolak, atau dikembalikan untuk perbaikan jenis 'file'.
    """
    sertifikat_qs = prestasi.sertifikat_set.all()
    for sertifikat in sertifikat_qs:
        hapus_file_cloudinary(sertifikat.file)
    sertifikat_qs.delete()
