"""Helper bersama untuk kelas siswa yang berlaku PER TAHUN AJARAN."""
from django.utils import timezone

from .models import Tahun_ajaran, Kelas, RiwayatKelas, LogPerubahanKelas


def tahun_ajaran_aktif():
    return Tahun_ajaran.objects.filter(status='aktif').order_by('-id').first()


def kelas_siswa_aktif(siswa):
    """Kelas siswa pada tahun ajaran aktif (dari RiwayatKelas), atau None."""
    tahun = tahun_ajaran_aktif()
    if tahun is None:
        return None
    riwayat = RiwayatKelas.objects.filter(siswa=siswa, tahun_ajaran=tahun).select_related('kelas').first()
    if riwayat:
        return riwayat.kelas
    # Data lama sebelum ada RiwayatKelas: cocokkan lewat nama kelas di tahun aktif.
    if siswa.kelas:
        return Kelas.objects.filter(tahun_ajaran=tahun, nama_kelas=siswa.kelas).first()
    return None


def tempatkan_ke_kelas(siswa, kelas, admin_user=None, alasan=None):
    """
    Tempatkan siswa ke `kelas` pada tahun ajaran milik kelas itu: tulis
    RiwayatKelas, catat LogPerubahanKelas, dan (kalau tahun ajarannya aktif)
    sinkronkan Siswa.kelas/tingkat. Return True bila ada perubahan.
    """
    lama = RiwayatKelas.objects.filter(siswa=siswa, tahun_ajaran=kelas.tahun_ajaran).first()
    if lama and lama.kelas_id == kelas.id:
        return False

    RiwayatKelas.objects.update_or_create(
        siswa=siswa, tahun_ajaran=kelas.tahun_ajaran,
        defaults={
            'kelas': kelas, 'tingkat': kelas.tingkat,
            'tanggal_penempatan': timezone.now(), 'diubah_oleh': admin_user,
        },
    )
    LogPerubahanKelas.objects.create(
        siswa=siswa,
        kelas_sebelumnya=lama.kelas if lama else None,
        kelas_baru=kelas,
        tahun_ajaran=kelas.tahun_ajaran,
        jenis_perubahan='perubahan_manual' if lama else 'penempatan_awal',
        alasan_perubahan=alasan,
        diubah_oleh=admin_user,
    )
    if kelas.tahun_ajaran.status == 'aktif':
        siswa.kelas = kelas.nama_kelas
        siswa.tingkat = kelas.tingkat
        siswa.save(update_fields=['kelas', 'tingkat'])
    return True