"""
Views Siswa untuk Admin & Super Admin
=====================================
Halaman kelola siswa (daftar, pagination, sorting, filter, statistik).
View untuk portal siswa sendiri (dashboard, lengkapi profil, QR code,
portofolio publik) ada di siswa_views.py -- sengaja dipisah.
"""
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import render

from .models import Siswa, Tahun_ajaran, DAFTAR_JURUSAN, DAFTAR_TINGKAT
from .decorators import role_required

PAGE_SIZE = 10

SORT_SISWA = {
    'nis_asc': ('nis',), 'nis_desc': ('-nis',),
    'username_asc': ('users__username',), 'username_desc': ('-users__username',),
    'nama_asc': ('nama',), 'nama_desc': ('-nama',),
    'tingkat_asc': ('tingkat', 'kelas', 'nama'), 'tingkat_desc': ('-tingkat', 'kelas', 'nama'),
}
DEFAULT_SORT_SISWA = 'nama_asc'


def _build_sort_toggle(current_sort, columns):
    """
    Untuk tiap kolom, tentukan value 'sort' berikutnya kalau header
    kolom di-klik lagi (asc <-> desc). Dipakai template sebagai
    `sort_toggle.nama_kolom`.
    """
    toggle = {}
    for col in columns:
        asc, desc = f'{col}_asc', f'{col}_desc'
        toggle[col] = desc if current_sort == asc else asc
    return toggle


@role_required('admin', 'super_admin')
def siswa_list(request):
    q = request.GET.get('q', '').strip()
    status_filter = request.GET.get('status', '').strip()
    f_kelas = request.GET.get('kelas', '').strip()
    f_jurusan = request.GET.get('jurusan', '').strip()
    f_tingkat = request.GET.get('tingkat', '').strip()
    sort = request.GET.get('sort', DEFAULT_SORT_SISWA)
    if sort not in SORT_SISWA:
        sort = DEFAULT_SORT_SISWA

    siswa_qs = Siswa.objects.select_related('users')

    if q:  # cari nama / NIS / kelas
        siswa_qs = siswa_qs.filter(
            Q(nama__icontains=q) | Q(nis__icontains=q) | Q(kelas__icontains=q)
        )
    if status_filter:
        siswa_qs = siswa_qs.filter(status=status_filter)
    if f_kelas:
        siswa_qs = siswa_qs.filter(kelas=f_kelas)
    if f_jurusan:
        siswa_qs = siswa_qs.filter(jurusan=f_jurusan)
    if f_tingkat:
        siswa_qs = siswa_qs.filter(tingkat=f_tingkat)

    siswa_qs = siswa_qs.order_by(*SORT_SISWA[sort])

    paginator = Paginator(siswa_qs, PAGE_SIZE)
    page_obj = paginator.get_page(request.GET.get('page'))

    ta_aktif = Tahun_ajaran.objects.filter(status='aktif').first()

    context = {
        'active_menu': 'siswa',  # dipakai sidebar base.html
        'page_obj': page_obj,
        'q': q,
        'sort': sort,
        'status_filter': status_filter,
        'f_kelas': f_kelas,
        'f_jurusan': f_jurusan,
        'f_tingkat': f_tingkat,
        'filter_aktif_count': sum(bool(v) for v in [f_kelas, f_jurusan, f_tingkat]),
        'sort_toggle': _build_sort_toggle(sort, ['nis', 'username', 'nama', 'tingkat']),
        'daftar_kelas': (
            Siswa.objects.exclude(kelas='').exclude(kelas__isnull=True)
            .values_list('kelas', flat=True).distinct().order_by('kelas')
        ),
        'daftar_jurusan': DAFTAR_JURUSAN,
        'daftar_tingkat': DAFTAR_TINGKAT,
        'item_label': 'siswa',  # dipakai partial pagination
        # Statistik: selalu dari seluruh data, tidak ikut terfilter
        'total_semua': Siswa.objects.count(),
        'total_aktif': Siswa.objects.filter(status='aktif').count(),
        'total_tidak_aktif': Siswa.objects.filter(status='nonaktif').count(),
        'total_alumni': Siswa.objects.filter(status='alumni').count(),
        'tahun_ajaran_aktif': ta_aktif.tahun_ajaran if ta_aktif else None,
    }
    return render(request, 'eprestasi/siswa/list.html', context)  # sesuaikan path template