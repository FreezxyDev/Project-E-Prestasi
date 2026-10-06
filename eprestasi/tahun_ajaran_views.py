"""
Views Tahun Ajaran (daftar + statistik) untuk Admin & Super Admin
=================================================================
Halaman daftar tahun ajaran dengan search, sorting, pagination, dan
aksi "Lihat Statistik" (jumlah siswa, jumlah prestasi, diagram lingkaran
siswa per jurusan). CRUD lain (tambah/edit/aktifkan/nonaktifkan/hapus)
tetap ada di views.py.

Definisi "siswa pada tahun ajaran X" = siswa yang punya baris RiwayatKelas
di tahun ajaran tersebut (lihat models.RiwayatKelas), bukan sekadar siswa
yang statusnya aktif sekarang. Jadi siswa yang belum ditempatkan ke kelas
lewat menu Pengelolaan Kelas belum ikut terhitung.
"""
from django.core.paginator import Paginator
from django.db.models import Count
from django.http import JsonResponse
from django.shortcuts import render, get_object_or_404

from .models import Siswa, Kesiswaan, Tahun_ajaran, Prestasi, RiwayatKelas
from .forms import TahunAjaranForm
from .decorators import role_required

PAGE_SIZE = 10

SORT_TAHUN_AJARAN = {
    'terbaru': ('-id',), 'terlama': ('id',),
    'nama_asc': ('tahun_ajaran', 'id'), 'nama_desc': ('-tahun_ajaran', '-id'),
    'status_asc': ('status', '-id'), 'status_desc': ('-status', '-id'),
    'siswa_asc': ('jumlah_siswa', '-id'), 'siswa_desc': ('-jumlah_siswa', '-id'),
    'prestasi_asc': ('jumlah_prestasi', '-id'), 'prestasi_desc': ('-jumlah_prestasi', '-id'),
}
DEFAULT_SORT_TAHUN_AJARAN = 'terbaru'


def _build_sort_toggle(current_sort, columns):
    toggle = {}
    for col in columns:
        asc, desc = f'{col}_asc', f'{col}_desc'
        toggle[col] = desc if current_sort == asc else asc
    return toggle


def _statistik_prestasi(qs):
    return {
        'total': qs.count(),
        'diterima': qs.filter(status='diterima').count(),
        'pending': qs.filter(status='pending').count(),
        'perbaikan': qs.filter(status='perbaikan').count(),
        'ditolak': qs.filter(status='ditolak').count(),
    }


@role_required('admin', 'super_admin')
def tahun_ajaran_list(request):
    q = request.GET.get('q', '').strip()
    sort = request.GET.get('sort', DEFAULT_SORT_TAHUN_AJARAN)
    if sort not in SORT_TAHUN_AJARAN:
        sort = DEFAULT_SORT_TAHUN_AJARAN

    daftar = Tahun_ajaran.objects.annotate(
        jumlah_siswa=Count('riwayat_kelas__siswa', distinct=True),
        jumlah_prestasi=Count('prestasi', distinct=True),
    )
    if q:
        daftar = daftar.filter(tahun_ajaran__icontains=q)
    daftar = daftar.order_by(*SORT_TAHUN_AJARAN[sort])

    paginator = Paginator(daftar, PAGE_SIZE)
    page_obj = paginator.get_page(request.GET.get('page'))

    # Statistik prestasi ikut filter pencarian; kosong -> semua tahun ajaran.
    prestasi_qs = Prestasi.objects.all()
    if q:
        prestasi_qs = prestasi_qs.filter(tahun_ajaran__tahun_ajaran__icontains=q)

    # Siswa/Kesiswaan tidak punya relasi langsung ke Tahun_ajaran, jadi
    # jumlah akun selalu dari seluruh sistem.
    statistik_akun = {
        'siswa_aktif': Siswa.objects.filter(status='aktif').count(),
        'siswa_alumni': Siswa.objects.filter(status='alumni').count(),
        'kesiswaan': Kesiswaan.objects.count(),
    }
    statistik_akun['total'] = sum(statistik_akun.values())

    context = {
        'active_menu': 'tahun_ajaran',
        'page_obj': page_obj,
        'item_label': 'tahun ajaran',  # dipakai partial pagination
        'q': q,
        'sort': sort,
        'sort_toggle': _build_sort_toggle(sort, ['nama', 'status', 'siswa', 'prestasi']),
        'statistik_prestasi': _statistik_prestasi(prestasi_qs),
        'statistik_akun': statistik_akun,
        'sedang_difilter': bool(q),
        'total_tahun_ajaran': Tahun_ajaran.objects.count(),
        'tahun_ajaran_aktif': Tahun_ajaran.objects.filter(status='aktif').first(),
        'form_tambah': TahunAjaranForm(initial={'status': 'nonaktif'}),
    }
    return render(request, 'eprestasi/tahun_ajaran/list.html', context)


@role_required('admin', 'super_admin')
def tahun_ajaran_statistik(request, tahun_ajaran_id):
    """
    Data statistik satu tahun ajaran dalam bentuk JSON, dipanggil lewat
    fetch() oleh modal "Lihat Statistik" di halaman daftar.
    """
    tahun = get_object_or_404(Tahun_ajaran, id=tahun_ajaran_id)

    # Siswa per jurusan. Jurusan siswa tetap selama bersekolah, jadi cukup
    # dibaca dari Siswa.jurusan. unique_together (siswa, tahun_ajaran) di
    # RiwayatKelas menjamin satu siswa hanya terhitung sekali.
    riwayat = RiwayatKelas.objects.filter(tahun_ajaran=tahun)
    hitung = {
        row['siswa__jurusan'] or '': row['n']
        for row in riwayat.values('siswa__jurusan').annotate(n=Count('siswa', distinct=True))
    }
    jurusan = [
        {'kode': kode, 'label': label, 'jumlah': hitung.pop(kode, 0)}
        for kode, label in Siswa.JURUSAN_CHOICES
    ]
    sisa = sum(hitung.values())  # jurusan kosong / di luar daftar
    if sisa:
        jurusan.append({'kode': '', 'label': 'Belum diisi', 'jumlah': sisa})

    prestasi = _statistik_prestasi(Prestasi.objects.filter(tahun_ajaran=tahun))

    return JsonResponse({
        'tahun_ajaran': tahun.tahun_ajaran,
        'status': tahun.status,
        'total_siswa': riwayat.count(),
        'prestasi': prestasi,
        'jurusan': jurusan,
    })