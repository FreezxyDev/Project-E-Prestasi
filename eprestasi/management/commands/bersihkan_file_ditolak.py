"""
Hapus file sertifikat, foto dokumentasi & dokumen Puspresnas dari prestasi yang SUDAH ditolak
sebelum perbaikan ini dipasang (foto dokumentasi lama masih tersisa di Cloudinary).

Pemakaian:  python manage.py bersihkan_file_ditolak
"""
from django.core.management.base import BaseCommand

from eprestasi.cloudinary_utils import hapus_semua_file_prestasi
from eprestasi.models import Prestasi


class Command(BaseCommand):
    help = 'Hapus sisa file (sertifikat & dokumentasi) milik prestasi berstatus ditolak.'

    def handle(self, *args, **options):
        jumlah = 0
        for prestasi in Prestasi.objects.filter(status='ditolak'):
            if (prestasi.sertifikat_set.exists() or prestasi.dokumentasi_set.exists()
                    or prestasi.dokumen_puspresnas):
                hapus_semua_file_prestasi(prestasi)
                jumlah += 1
        self.stdout.write(self.style.SUCCESS(f'Selesai. {jumlah} prestasi ditolak dibersihkan.'))
