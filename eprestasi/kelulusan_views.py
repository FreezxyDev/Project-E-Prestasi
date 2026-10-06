"""
Halaman Kelulusan & Alumni
==========================
Halaman khusus untuk siswa tingkat XII: memproses kelulusan (aktif -> lulus
-> alumni) dan menampilkan data alumni. Tidak ada model baru -- semua
memakai field yang sudah ada di Siswa (status, status_kelulusan,
tanggal_kelulusan) supaya data historis & relasi prestasi tetap terjaga.
"""
from django.shortcuts import render, redirect
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q, OuterRef, Subquery
from django.utils import timezone

from .models import Siswa, RiwayatKelas, DAFTAR_JURUSAN
from .decorators import role_required
from .log_utils import catat_aktivitas

PAGE_SIZE = 10

SORT_KELULUSAN = {
    'nama_asc': ('nama',), 'nama_desc': ('-nama',),
    'nis_asc': ('nis',), 'nis_desc': ('-nis',),
    'kelas_asc': ('kelas', 'nama'), 'kelas_desc': ('-kelas', 'nama'),
    'jurusan_asc': ('jurusan', 'nama'), 'jurusan_desc': ('-jurusan', 'nama'),
    'tahun_ajaran_asc': ('tahun_ajaran_label', 'nama'), 'tahun_ajaran_desc': ('-tahun_ajaran_label', 'nama'),
    'status_kelulusan_asc': ('status_kelulusan', 'nama'), 'status_kelulusan_desc': ('-status_kelulusan', 'nama'),
    'status_asc': ('status', 'nama'), 'status_desc': ('-status', 'nama'),
    'tanggal_asc': ('tanggal_kelulusan', 'nama'), 'tanggal_desc': ('-tanggal_kelulusan', 'nama'),
}
DEFAULT_SORT_KELULUSAN = 'nama_asc'

SORT_ALUMNI = {
    'nama_asc': ('nama',), 'nama_desc': ('-nama',),
    'nis_asc': ('nis',), 'nis_desc': ('-nis',),
    'jurusan_asc': ('jurusan', 'nama'), 'jurusan_desc': ('-jurusan', 'nama'),
    'kelas_asc': ('kelas', 'nama'), 'kelas_desc': ('-kelas', 'nama'),
    'tahun_lulus_asc': ('tanggal_kelulusan', 'nama'), 'tahun_lulus_desc': ('-tanggal_kelulusan', 'nama'),
}
DEFAULT_SORT_ALUMNI = 'tahun_lulus_desc'

STATUS_KELULUSAN_LABEL = dict(Siswa.STATUS_KELULUSAN_CHOICES)
STATUS_SISWA_LABEL = {'aktif': 'Aktif', 'nonaktif': 'Nonaktif', 'alumni': 'Alumni'}


def _build_sort_toggle(current_sort, columns):
    """
    Untuk setiap nama kolom di `columns`, tentukan value 'sort' berikutnya
    kalau kolom itu di-klik lagi (toggle asc <-> desc). Dipakai supaya
    template header tabel tidak perlu logika if/else -- cukup
    `sort_toggle.nama_kolom`.
    """
    toggle = {}
    for col in columns:
        asc, desc = f'{col}_asc', f'{col}_desc'
        toggle[col] = desc if current_sort == asc else asc
    return toggle


def _annotate_tahun_ajaran(qs):
    """
    Lampirkan label tahun ajaran terakhir siswa berada di tingkat XII,
    diambil dari RiwayatKelas (kelas siswa bisa berubah tiap tahun ajaran,
    lihat models.py). Kalau siswa belum pernah tercatat di RiwayatKelas
    (misal input manual lama), label ini kosong.
    """
    latest = (
        RiwayatKelas.objects.filter(siswa=OuterRef('pk'), tingkat=12)
        .order_by('-tahun_ajaran_id')
        .values('tahun_ajaran__tahun_ajaran')[:1]
    )
    return qs.annotate(tahun_ajaran_label=Subquery(latest))


@role_required('admin', 'super_admin')
def kelulusan_alumni(request):
    tab = request.GET.get('tab', 'kelulusan')
    if tab not in ('kelulusan', 'alumni'):
        tab = 'kelulusan'

    kelas_xii_qs = Siswa.objects.filter(tingkat=12)
    statistik = {
        'total_xii': kelas_xii_qs.count(),
        'siap_diproses': kelas_xii_qs.filter(status='aktif', status_kelulusan='belum_diproses').count(),
        'lulus': Siswa.objects.filter(status_kelulusan='lulus').count(),
        'belum_lulus': Siswa.objects.filter(status_kelulusan='tidak_lulus').count(),
        'alumni': Siswa.objects.filter(status='alumni').count(),
    }

    context = {
        'active_menu': 'kelulusan_alumni',
        'active_tab': tab,
        'statistik': statistik,
        'daftar_jurusan': DAFTAR_JURUSAN,
    }

    if tab == 'alumni':
        context.update(_build_alumni_context(request))
    else:
        context.update(_build_kelulusan_context(request))

    return render(request, 'eprestasi/kelulusan/list.html', context)


def _build_kelulusan_context(request):
    q = request.GET.get('q', '').strip()
    f_tahun_ajaran = request.GET.get('tahun_ajaran', '').strip()
    f_kelas = request.GET.get('kelas', '').strip()
    f_jurusan = request.GET.get('jurusan', '').strip()
    f_status_kelulusan = request.GET.get('status_kelulusan', '').strip()
    f_status_siswa = request.GET.get('status_siswa', '').strip()
    sort = request.GET.get('sort', DEFAULT_SORT_KELULUSAN)
    if sort not in SORT_KELULUSAN:
        sort = DEFAULT_SORT_KELULUSAN

    siswa_qs = Siswa.objects.filter(tingkat=12).select_related('users')
    siswa_qs = _annotate_tahun_ajaran(siswa_qs)

    if q:
        siswa_qs = siswa_qs.filter(Q(nama__icontains=q) | Q(nis__icontains=q))
    if f_tahun_ajaran:
        siswa_qs = siswa_qs.filter(riwayat_kelas__tahun_ajaran_id=f_tahun_ajaran, riwayat_kelas__tingkat=12)
    if f_kelas:
        siswa_qs = siswa_qs.filter(kelas=f_kelas)
    if f_jurusan:
        siswa_qs = siswa_qs.filter(jurusan=f_jurusan)
    if f_status_kelulusan:
        siswa_qs = siswa_qs.filter(status_kelulusan=f_status_kelulusan)
    if f_status_siswa:
        siswa_qs = siswa_qs.filter(status=f_status_siswa)

    siswa_qs = siswa_qs.distinct().order_by(*SORT_KELULUSAN[sort])

    sort_toggle = _build_sort_toggle(sort, [
        'nis', 'nama', 'kelas', 'jurusan', 'tahun_ajaran', 'status_kelulusan', 'status', 'tanggal',
    ])

    daftar_kelas_xii = (
        Siswa.objects.filter(tingkat=12).exclude(kelas='').exclude(kelas__isnull=True)
        .values_list('kelas', flat=True).distinct().order_by('kelas')
    )
    daftar_tahun_ajaran = (
        RiwayatKelas.objects.filter(tingkat=12).select_related('tahun_ajaran')
        .values_list('tahun_ajaran_id', 'tahun_ajaran__tahun_ajaran').distinct().order_by('-tahun_ajaran_id')
    )

    paginator = Paginator(siswa_qs, PAGE_SIZE)
    page_obj = paginator.get_page(request.GET.get('page'))

    filter_aktif = sum(bool(v) for v in [f_tahun_ajaran, f_kelas, f_jurusan, f_status_kelulusan, f_status_siswa])

    return {
        'page_obj': page_obj,
        'q': q,
        'sort': sort,
        'f_tahun_ajaran': f_tahun_ajaran,
        'f_kelas': f_kelas,
        'f_jurusan': f_jurusan,
        'f_status_kelulusan': f_status_kelulusan,
        'f_status_siswa': f_status_siswa,
        'filter_aktif_count': filter_aktif,
        'daftar_kelas_xii': daftar_kelas_xii,
        'daftar_tahun_ajaran': daftar_tahun_ajaran,
        'status_kelulusan_choices': Siswa.STATUS_KELULUSAN_CHOICES,
        'sort_toggle': sort_toggle,
        'item_label': 'siswa',
    }


def _build_alumni_context(request):
    q = request.GET.get('q', '').strip()
    f_tahun_lulus = request.GET.get('tahun_lulus', '').strip()
    f_jurusan = request.GET.get('jurusan', '').strip()
    f_kelas = request.GET.get('kelas', '').strip()
    sort = request.GET.get('sort', DEFAULT_SORT_ALUMNI)
    if sort not in SORT_ALUMNI:
        sort = DEFAULT_SORT_ALUMNI

    alumni_qs = Siswa.objects.filter(status='alumni').select_related('users')

    if q:
        alumni_qs = alumni_qs.filter(Q(nama__icontains=q) | Q(nis__icontains=q))
    if f_tahun_lulus:
        alumni_qs = alumni_qs.filter(tanggal_kelulusan__year=f_tahun_lulus)
    if f_jurusan:
        alumni_qs = alumni_qs.filter(jurusan=f_jurusan)
    if f_kelas:
        alumni_qs = alumni_qs.filter(kelas=f_kelas)

    alumni_qs = alumni_qs.order_by(*SORT_ALUMNI[sort])

    sort_toggle = _build_sort_toggle(sort, ['nis', 'nama', 'jurusan', 'kelas', 'tahun_lulus'])

    daftar_tahun_lulus = (
        Siswa.objects.filter(status='alumni').exclude(tanggal_kelulusan__isnull=True)
        .dates('tanggal_kelulusan', 'year', order='DESC')
    )
    daftar_kelas_alumni = (
        Siswa.objects.filter(status='alumni').exclude(kelas='').exclude(kelas__isnull=True)
        .values_list('kelas', flat=True).distinct().order_by('kelas')
    )

    paginator = Paginator(alumni_qs, PAGE_SIZE)
    page_obj = paginator.get_page(request.GET.get('page'))

    filter_aktif = sum(bool(v) for v in [f_tahun_lulus, f_jurusan, f_kelas])

    return {
        'page_obj': page_obj,
        'q': q,
        'sort': sort,
        'f_tahun_lulus': f_tahun_lulus,
        'f_jurusan': f_jurusan,
        'f_kelas': f_kelas,
        'filter_aktif_count': filter_aktif,
        'daftar_tahun_lulus': [d.year for d in daftar_tahun_lulus],
        'daftar_kelas_alumni': daftar_kelas_alumni,
        'sort_toggle': sort_toggle,
        'item_label': 'alumni',
    }


def _kembali_ke_kelulusan(request, tab='kelulusan'):
    from django.urls import reverse
    qd = request.POST.copy()
    qd.pop('siswa_ids', None)
    qd['tab'] = tab
    query = qd.urlencode()
    url = reverse('kelulusan_alumni')
    return redirect(f'{url}?{query}' if query else f'{url}?tab={tab}')


@role_required('admin', 'super_admin')
def proses_kelulusan(request):
    """
    Aksi massal "Proses Kelulusan": siswa terpilih (tingkat XII) ditetapkan
    Lulus -> status siswa otomatis berubah jadi Alumni. Data siswa TIDAK
    dihapus, riwayat & relasi prestasi tetap tersambung.
    """
    if request.method != 'POST':
        return redirect('kelulusan_alumni')

    siswa_ids = request.POST.getlist('siswa_ids')
    if not siswa_ids:
        messages.error(request, 'Pilih minimal satu siswa yang akan diproses kelulusannya.')
        return _kembali_ke_kelulusan(request)

    siswa_terpilih = Siswa.objects.filter(id__in=siswa_ids, tingkat=12)
    hari_ini = timezone.localdate()
    nama_terproses = list(siswa_terpilih.values_list('nama', flat=True))
    jumlah = siswa_terpilih.update(status_kelulusan='lulus', status='alumni', tanggal_kelulusan=hari_ini)

    if jumlah:
        catat_aktivitas(
            request, 'kelulusan_diproses',
            'Admin memproses kelulusan siswa',
            f'{jumlah} siswa kelas XII ditetapkan Lulus dan berpindah status menjadi Alumni: '
            f'{", ".join(nama_terproses[:10])}{" dan lainnya" if jumlah > 10 else ""}.',
            modul='kelulusan',
        )
        messages.success(request, f'{jumlah} siswa berhasil ditetapkan sebagai Lulus dan kini berstatus Alumni.')
    else:
        messages.warning(request, 'Tidak ada siswa yang berhasil diproses (pastikan siswa berada di tingkat XII).')

    return _kembali_ke_kelulusan(request)


@role_required('admin', 'super_admin')
def tandai_tidak_lulus(request):
    """
    Aksi sekunder: menandai siswa tingkat XII sebagai Tidak Lulus. Berbeda
    dari "Proses Kelulusan", status siswa TIDAK berubah menjadi alumni
    (siswa tetap aktif, hanya status_kelulusan yang berubah), karena siswa
    masih berpotensi mengulang/diproses ulang di kemudian hari.
    """
    if request.method != 'POST':
        return redirect('kelulusan_alumni')

    siswa_ids = request.POST.getlist('siswa_ids')
    if not siswa_ids:
        messages.error(request, 'Pilih minimal satu siswa terlebih dahulu.')
        return _kembali_ke_kelulusan(request)

    siswa_terpilih = Siswa.objects.filter(id__in=siswa_ids, tingkat=12)
    nama_terproses = list(siswa_terpilih.values_list('nama', flat=True))
    jumlah = siswa_terpilih.update(status_kelulusan='tidak_lulus')

    if jumlah:
        catat_aktivitas(
            request, 'kelulusan_diproses',
            'Admin menandai siswa tidak lulus',
            f'{jumlah} siswa kelas XII ditandai Tidak Lulus: '
            f'{", ".join(nama_terproses[:10])}{" dan lainnya" if jumlah > 10 else ""}.',
            modul='kelulusan',
        )
        messages.success(request, f'{jumlah} siswa berhasil ditandai sebagai Tidak Lulus.')

    return _kembali_ke_kelulusan(request)