"""
View drill-down: Tahun Ajaran -> Kelas -> Siswa.

Alur: halaman daftar Tahun Ajaran -> tombol "Kelas" -> daftar kelas pada tahun
tersebut -> klik kelas -> daftar siswa kelas itu.
"""
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, render

from .decorators import role_required
from .models import (
    Tahun_ajaran, Kelas, Siswa, RiwayatKelas,
    DAFTAR_JURUSAN, DAFTAR_TINGKAT, TINGKAT_KE_ROMAWI,
)


@role_required('admin', 'super_admin')
def tahun_ajaran_kelas(request, tahun_id):
    """Daftar kelas pada satu tahun ajaran."""
    tahun = get_object_or_404(Tahun_ajaran, pk=tahun_id)
    q = request.GET.get('q', '').strip()
    tingkat_filter = request.GET.get('tingkat', '')
    jurusan_filter = request.GET.get('jurusan', '')

    # jumlah_siswa di model Kelas adalah @property -> pakai annotate 'jumlah_siswa_hitung'
    kelas_qs = (Kelas.objects.filter(tahun_ajaran=tahun)
                .annotate(jumlah_siswa_hitung=Count('riwayat_kelas', distinct=True))
                .order_by('tingkat', 'jurusan', 'nama_kelas'))

    if q:
        kelas_qs = kelas_qs.filter(nama_kelas__icontains=q)
    if tingkat_filter.isdigit():
        kelas_qs = kelas_qs.filter(tingkat=int(tingkat_filter))
    if jurusan_filter:
        kelas_qs = kelas_qs.filter(jurusan=jurusan_filter)

    daftar_kelas = list(kelas_qs)  # tingkat_romawi & jumlah_siswa sudah property di model

    total_kelas = len(daftar_kelas)
    total_siswa = sum(k.jumlah_siswa for k in daftar_kelas)

    # Siswa aktif yang belum ditempatkan ke kelas mana pun pada tahun ajaran ini
    sudah_punya_kelas = RiwayatKelas.objects.filter(tahun_ajaran=tahun).values('siswa_id')
    tanpa_kelas = Siswa.objects.filter(status='aktif').exclude(id__in=sudah_punya_kelas).count()

    return render(request, 'eprestasi/tahun_ajaran/kelas_list.html', {
        'active_menu': 'tahun_ajaran',
        'tahun': tahun,
        'daftar_kelas': daftar_kelas,
        'total_kelas': total_kelas,
        'total_siswa': total_siswa,
        'rata_siswa': round(total_siswa / total_kelas) if total_kelas else 0,
        'maks_siswa': max([k.jumlah_siswa for k in daftar_kelas] + [1]),
        'tanpa_kelas': tanpa_kelas,
        'q': q,
        'tingkat_filter': tingkat_filter,
        'jurusan_filter': jurusan_filter,
        'daftar_tingkat': [(n, TINGKAT_KE_ROMAWI.get(n, n)) for n, _ in DAFTAR_TINGKAT],
        'daftar_jurusan': list(DAFTAR_JURUSAN),
    })


@role_required('admin', 'super_admin')
def tahun_ajaran_kelas_siswa(request, tahun_id, kelas_id):
    """Daftar siswa pada satu kelas di satu tahun ajaran."""
    tahun = get_object_or_404(Tahun_ajaran, pk=tahun_id)
    kelas = get_object_or_404(Kelas, pk=kelas_id, tahun_ajaran=tahun)
    q = request.GET.get('q', '').strip()

    semua = Siswa.objects.filter(riwayat_kelas__kelas=kelas).distinct()

    siswa_qs = (semua
                .annotate(jumlah_prestasi=Count('prestasi', distinct=True),
                          jumlah_diterima=Count('prestasi', filter=Q(prestasi__status='diterima'),
                                                distinct=True))
                .order_by('nama', 'nis'))
    if q:
        siswa_qs = siswa_qs.filter(Q(nis__icontains=q) | Q(nama__icontains=q))

    page_obj = Paginator(siswa_qs, 25).get_page(request.GET.get('page'))

    # Total prestasi dihitung untuk SELURUH siswa kelas (bukan hanya halaman ini)
    total = semua.aggregate(
        prestasi=Count('prestasi', distinct=True),
        diterima=Count('prestasi', filter=Q(prestasi__status='diterima'), distinct=True),
    )

    return render(request, 'eprestasi/tahun_ajaran/siswa_kelas.html', {
        'active_menu': 'tahun_ajaran',
        'tahun': tahun,
        'kelas': kelas,
        'page_obj': page_obj,
        'q': q,
        'total_siswa': semua.count(),
        'total_aktif': semua.filter(status='aktif').count(),
        'total_prestasi': total['prestasi'],
        'total_diterima': total['diterima'],
    })