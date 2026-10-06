from eprestasi.models import Prestasi, Kesiswaan, NotifikasiDibaca, Siswa, NotifikasiSiswa

BATAS_NOTIF = 5


def notifikasi_kesiswaan(request):
    """
    Notifikasi bel di topnav. Nama fungsi dipertahankan supaya settings.py
    tidak perlu diubah, tapi sekarang melayani dua role:
    - kesiswaan : pengajuan pending (dibaca/belum per akun kesiswaan)
    - siswa     : hasil verifikasi prestasi miliknya (NotifikasiSiswa)
    """
    role = request.session.get('role')
    user_id = request.session.get('user_id')

    if role == 'siswa':
        siswa = Siswa.objects.filter(users_id=user_id).first()
        if siswa is None:
            return {}
        qs = NotifikasiSiswa.objects.filter(siswa=siswa)
        return {
            'notif_jumlah': qs.filter(dibaca=False).count(),
            'notif_list': list(qs[:BATAS_NOTIF]),
            'notif_batas': BATAS_NOTIF,
        }

    if role != 'kesiswaan':
        return {}

    kesiswaan = Kesiswaan.objects.filter(user_id=user_id).first()
    if kesiswaan is None:
        return {}

    pending = Prestasi.objects.filter(status='pending')
    belum_dibaca = pending.exclude(notifikasi_dibaca__kesiswaan=kesiswaan).count()

    items = list(pending.select_related('siswa').order_by('-tanggal_upload')[:BATAS_NOTIF])
    sudah_dibaca_ids = set(
        NotifikasiDibaca.objects
        .filter(kesiswaan=kesiswaan, prestasi_id__in=[p.id for p in items])
        .values_list('prestasi_id', flat=True)
    )
    for p in items:
        p.sudah_dibaca = p.id in sudah_dibaca_ids

    return {
        'notif_jumlah': belum_dibaca,
        'notif_total_pending': pending.count(),
        'notif_list': items,
        'notif_batas': BATAS_NOTIF,
    }