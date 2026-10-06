# PORTAL KESISWAAN -- dashboard, verifikasi, riwayat, profil.
# Semua tabel prestasi memakai satu set filter/sorting/pagination yang sama
# (lihat _baca_filter, _terapkan_filter, dan _susun_halaman_prestasi).

from urllib.parse import urlencode

from django.core.paginator import Paginator
from django.db.models import Q, Count, F, OuterRef, Subquery, Max, Case, When, Value, IntegerField
from django.db.models.functions import Coalesce, TruncMonth
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_POST
from django.utils.http import url_has_allowed_host_and_scheme
from eprestasi.models import NotifikasiDibaca, NotifikasiSiswa

from eprestasi.decorators import role_required
from eprestasi.models import (
    Siswa, Kesiswaan, Prestasi, Tahun_ajaran, Kelas, RiwayatKelas, DAFTAR_TINGKAT,
)
from eprestasi.forms import (
    KesiswaanProfilForm, VerifikasiPrestasiForm, TINGKAT_PRESTASI_CHOICES,
)
from eprestasi.cloudinary_utils import hapus_sertifikat_prestasi
from eprestasi.log_utils import catat_aktivitas

PAGE_SIZE = 10


# ==========================================
# HELPER FUNCTIONS
# ==========================================

def _get_kesiswaan(request):
    """Ambil data Kesiswaan milik user yang sedang login (dari session)."""
    return (
        Kesiswaan.objects
        .filter(user_id=request.session.get('user_id'))
        .select_related('user')
        .first()
    )


def _guard_kesiswaan(request):
    """Wajib login sebagai kesiswaan DAN profil sudah lengkap."""
    kesiswaan = _get_kesiswaan(request)

    if kesiswaan is None:
        messages.error(request, 'Data kesiswaan tidak ditemukan.')
        return None, redirect('logout')

    if not kesiswaan.profil_lengkap:
        messages.warning(request, 'Lengkapi profil Anda dulu.')
        return None, redirect('kesiswaan_lengkapi_profil')

    return kesiswaan, None

def _log_verifikasi_terbaru(limit=3):
    """`limit` aktivitas verifikasi terakhir (diterima / perbaikan / ditolak)."""
    ikon = {
        'diterima':  ('bi-check-circle', 'success', 'Prestasi diterima'),
        'perbaikan': ('bi-tools', 'pending', 'Dikembalikan untuk perbaikan'),
        'ditolak':   ('bi-x-circle', 'danger', 'Prestasi ditolak'),
    }
    qs = (
        Prestasi.objects
        .filter(status__in=STATUS_TERVERIFIKASI, tanggal_verifikasi__isnull=False)
        .select_related('siswa', 'kesiswaan')
        .order_by('-tanggal_verifikasi')[:limit]
    )
    log = []
    for p in qs:
        icon, warna, judul = ikon[p.status]
        oleh = (p.kesiswaan.nama or p.kesiswaan.nip) if p.kesiswaan else '-'
        log.append({
            'waktu': p.tanggal_verifikasi,
            'icon': icon,
            'status': warna,
            'judul': judul,
            'deskripsi': f'"{p.nama_prestasi}" milik {p.siswa.nama} · oleh {oleh}',
        })
    return log

def _anotasi_kelas_riwayat(qs):
    """
    Tempelkan kelas/jurusan/tingkat siswa PADA TAHUN AJARAN prestasi itu
    (dari RiwayatKelas), bukan kelas siswa hari ini. Kalau riwayatnya tidak ada
    (data lama sebelum fitur kelas), jatuh ke nilai di data siswa.
    """
    riwayat = RiwayatKelas.objects.filter(
        siswa=OuterRef('siswa'), tahun_ajaran=OuterRef('tahun_ajaran')
    )
    return qs.annotate(
        kelas_nama=Coalesce(Subquery(riwayat.values('kelas__nama_kelas')[:1]), F('siswa__kelas')),
        kelas_jurusan=Coalesce(Subquery(riwayat.values('kelas__jurusan')[:1]), F('siswa__jurusan')),
        kelas_tingkat=Coalesce(Subquery(riwayat.values('tingkat')[:1]), F('siswa__tingkat')),
    )
# ==========================================
# FILTER + SORTING PRESTASI (dipakai 3 halaman)
# ==========================================

STATUS_LABEL = {
    'pending': 'Pending', 'diterima': 'Diterima',
    'perbaikan': 'Perbaikan', 'ditolak': 'Ditolak',
}
BOBOT_TINGKAT = {'sekolah': 1, 'kabupaten/kota': 2, 'provinsi': 3, 'nasional': 4, 'internasional': 5}
BOBOT_KE_TINGKAT = {v: k for k, v in BOBOT_TINGKAT.items()}
LABEL_TINGKAT = {1: 'Sekolah', 2: 'Kabupaten/Kota', 3: 'Provinsi', 4: 'Nasional', 5: 'Internasional'}
NAMA_BULAN = ['Jan', 'Feb', 'Mar', 'Apr', 'Mei', 'Jun', 'Jul', 'Agu', 'Sep', 'Okt', 'Nov', 'Des']
STATUS_TERVERIFIKASI = ('diterima', 'perbaikan', 'ditolak')

KATEGORI_CHOICES = [(v, v.replace('-', ' ').title()) for v, _ in Prestasi._meta.get_field('kategori_prestasi').choices]
JENIS_PERBAIKAN_CHOICES = [('data', 'Perbaikan Data'), ('file', 'Perbaikan File')]
PUSPRESNAS_CHOICES = [('sudah', 'Sudah ada'), ('belum', 'Belum ada')]

SORT_PRESTASI = {
    'siswa_asc': ('siswa__nama', 'id'), 'siswa_desc': ('-siswa__nama', 'id'),
    'prestasi_asc': ('nama_prestasi', 'id'), 'prestasi_desc': ('-nama_prestasi', 'id'),
    'kategori_asc': ('kategori_prestasi', 'id'), 'kategori_desc': ('-kategori_prestasi', 'id'),
    'tingkat_asc': ('tingkat_prestasi', 'id'), 'tingkat_desc': ('-tingkat_prestasi', 'id'),
    'kelas_asc': ('kelas_nama', 'siswa__nama'), 'kelas_desc': ('-kelas_nama', 'siswa__nama'),
    'status_asc': ('status', '-tanggal_upload'), 'status_desc': ('-status', '-tanggal_upload'),
    'tanggal_asc': ('tanggal_prestasi', 'id'), 'tanggal_desc': ('-tanggal_prestasi', 'id'),
    'upload_asc': ('tanggal_upload', 'id'), 'upload_desc': ('-tanggal_upload', '-id'),
    'verif_asc': ('tanggal_verifikasi', 'id'), 'verif_desc': ('-tanggal_verifikasi', '-id'),
}
SORT_KOLOM = ['siswa', 'prestasi', 'kategori', 'tingkat', 'kelas', 'status', 'tanggal', 'upload', 'verif']

# Kunci filter dari querystring. 'q' & 'status' ditangani terpisah dari
# "filter lanjutan" supaya tidak ikut dihitung di badge tombol Filter.
FILTER_LANJUTAN = [
    'kategori', 'tingkat_prestasi', 'puspresnas', 'jenis_perbaikan',
    'kelas', 'tingkat_siswa', 'jurusan', 'tahun',
    'tanggal_dari', 'tanggal_sampai', 'upload_dari', 'upload_sampai',
    'verifikator', 'verif_dari', 'verif_sampai',
]


def _build_sort_toggle(current_sort, columns):
    toggle = {}
    for col in columns:
        asc, desc = f'{col}_asc', f'{col}_desc'
        toggle[col] = desc if current_sort == asc else asc
    return toggle


def _baca_filter(request):
    """Baca semua parameter filter dari querystring (sudah di-strip)."""
    f = {k: request.GET.get(k, '').strip() for k in ['q', 'status'] + FILTER_LANJUTAN}
    # tanggal yang tidak valid dibuang, bukan bikin halaman error
    for k in ('tanggal_dari', 'tanggal_sampai', 'upload_dari', 'upload_sampai', 'verif_dari', 'verif_sampai'):
        if f[k] and parse_date(f[k]) is None:
            f[k] = ''
    return f


def _terapkan_filter(qs, f, kesiswaan, abaikan=()):
    """
    Terapkan semua filter ke queryset Prestasi. `abaikan` berisi nama filter
    yang dilewati (dipakai supaya kartu statistik status tidak ikut terfilter
    oleh status itu sendiri).
    """
    if f['q'] and 'q' not in abaikan:
        qs = qs.filter(
            Q(siswa__nama__icontains=f['q']) | Q(siswa__nis__icontains=f['q'])
            | Q(nama_prestasi__icontains=f['q']) | Q(penyelenggara__icontains=f['q'])
        )
    if f['status'] in STATUS_LABEL and 'status' not in abaikan:
        qs = qs.filter(status=f['status'])
    if f['kategori']:
        qs = qs.filter(kategori_prestasi=f['kategori'])
    if f['tingkat_prestasi']:
        qs = qs.filter(tingkat_prestasi=f['tingkat_prestasi'])
    if f['jenis_perbaikan']:
        qs = qs.filter(jenis_perbaikan=f['jenis_perbaikan'])
    if f['kelas']:
        qs = qs.filter(kelas_nama=f['kelas'])
    if f['tingkat_siswa'].isdigit():
        qs = qs.filter(kelas_tingkat=int(f['tingkat_siswa']))
    if f['jurusan']:
        qs = qs.filter(kelas_jurusan=f['jurusan'])
    if f['tahun'].isdigit():
        qs = qs.filter(tahun_ajaran_id=int(f['tahun']))

    sudah_puspresnas = (
        (Q(kode_puspresnas__isnull=False) & ~Q(kode_puspresnas=''))
        | (Q(dokumen_puspresnas__isnull=False) & ~Q(dokumen_puspresnas=''))
    )
    if f['puspresnas'] == 'sudah':
        qs = qs.filter(sudah_puspresnas)
    elif f['puspresnas'] == 'belum':
        qs = qs.exclude(sudah_puspresnas)

    for kunci, lookup in (
        ('tanggal_dari', 'tanggal_prestasi__gte'), ('tanggal_sampai', 'tanggal_prestasi__lte'),
        ('upload_dari', 'tanggal_upload__date__gte'), ('upload_sampai', 'tanggal_upload__date__lte'),
        ('verif_dari', 'tanggal_verifikasi__date__gte'), ('verif_sampai', 'tanggal_verifikasi__date__lte'),
    ):
        if f[kunci]:
            qs = qs.filter(**{lookup: parse_date(f[kunci])})

    if f['verifikator'] == 'saya':
        qs = qs.filter(kesiswaan=kesiswaan)
    elif f['verifikator'] == 'belum':
        qs = qs.filter(kesiswaan__isnull=True)
    elif f['verifikator'].isdigit():
        qs = qs.filter(kesiswaan_id=int(f['verifikator']))
    return qs


def _chip_filter(request, f, opsi):
    """Daftar chip filter aktif + querystring untuk menghapus tiap chip."""
    tahun_label = {str(i): t for i, t in opsi['tahun_list']}
    verifikator_label = {'saya': 'Saya', 'belum': 'Belum ada'}
    verifikator_label.update({str(k.id): (k.nama or k.nip) for k in opsi['verifikator_list']})

    def tampil(key, nilai):
        return {
            'q': f'Cari: "{nilai}"',
            'status': f'Status: {STATUS_LABEL.get(nilai, nilai)}',
            'kategori': f'Kategori: {dict(KATEGORI_CHOICES).get(nilai, nilai)}',
            'tingkat_prestasi': f'Tingkat: {dict(TINGKAT_PRESTASI_CHOICES).get(nilai, nilai)}',
            'jenis_perbaikan': f'Jenis perbaikan: {dict(JENIS_PERBAIKAN_CHOICES).get(nilai, nilai)}',
            'puspresnas': f'Puspresnas: {dict(PUSPRESNAS_CHOICES).get(nilai, nilai)}',
            'kelas': f'Kelas: {nilai}',
            'tingkat_siswa': f'Tingkat siswa: {dict(DAFTAR_TINGKAT).get(int(nilai) if nilai.isdigit() else nilai, nilai)}',            'jurusan': f'Jurusan: {nilai}',
            'tahun': f'Tahun ajaran: {tahun_label.get(nilai, nilai)}',
            'verifikator': f'Verifikator: {verifikator_label.get(nilai, nilai)}',
            'tanggal_dari': f'Prestasi dari {nilai}', 'tanggal_sampai': f'Prestasi sampai {nilai}',
            'upload_dari': f'Upload dari {nilai}', 'upload_sampai': f'Upload sampai {nilai}',
            'verif_dari': f'Verifikasi dari {nilai}', 'verif_sampai': f'Verifikasi sampai {nilai}',
        }[key]

    chips = []
    for key in ['q', 'status'] + FILTER_LANJUTAN:
        if f[key]:
            qd = request.GET.copy()
            qd.pop(key, None)
            qd.pop('page', None)
            chips.append({'key': key, 'label': tampil(key, f[key]), 'hapus_qs': qd.urlencode()})
    return chips

def _opsi_filter(tahun_id=''):
    kelas_qs = Kelas.objects.all()
    if tahun_id and str(tahun_id).isdigit():
        kelas_qs = kelas_qs.filter(tahun_ajaran_id=int(tahun_id))
    nama_kelas = kelas_qs.order_by('nama_kelas').values_list('nama_kelas', flat=True).distinct()

    return {
        'kategori_choices': KATEGORI_CHOICES,
        'tingkat_prestasi_choices': TINGKAT_PRESTASI_CHOICES,
        'jenis_perbaikan_choices': JENIS_PERBAIKAN_CHOICES,
        'puspresnas_choices': PUSPRESNAS_CHOICES,
        'kelas_choices': [(n, n) for n in nama_kelas],
        'tingkat_siswa_choices': DAFTAR_TINGKAT,
        'jurusan_choices': Siswa.JURUSAN_CHOICES,
        'tahun_list': list(Tahun_ajaran.objects.order_by('-id').values_list('id', 'tahun_ajaran')),
        'verifikator_list': list(Kesiswaan.objects.exclude(nama='').order_by('nama')),
    }

def _susun_halaman_prestasi(request, kesiswaan, *, qs_awal, sort_default, status_pilihan=None, status_default=None, tahun_default=None):
    f = _baca_filter(request)
    if status_default and 'status' not in request.GET:
        f['status'] = status_default
    if tahun_default and 'tahun' not in request.GET:
        f['tahun'] = str(tahun_default)
    if status_pilihan and f['status'] not in status_pilihan:
        f['status'] = ''
    # ... sisanya tidak berubah
        
    sort = request.GET.get('sort', sort_default)
    if sort not in SORT_PRESTASI:
        sort = sort_default

    base_qs = _anotasi_kelas_riwayat(
        qs_awal.select_related('siswa', 'tahun_ajaran', 'kesiswaan')
    )
    # Statistik status dihitung dari hasil filter KECUALI filter status-nya
    # sendiri, supaya kartu/tab tetap menunjukkan sebaran seluruh status.
    tanpa_status = _terapkan_filter(base_qs, f, kesiswaan, abaikan=('status',))
    hitung = {r['status']: r['n'] for r in tanpa_status.values('status').annotate(n=Count('id'))}
    statistik = {s: hitung.get(s, 0) for s in STATUS_LABEL}
    statistik['total'] = sum(statistik.values())

    hasil = _terapkan_filter(base_qs, f, kesiswaan).order_by(*SORT_PRESTASI[sort])
    page_obj = Paginator(hasil, PAGE_SIZE).get_page(request.GET.get('page'))

    opsi = _opsi_filter(f['tahun'])
    jumlah_lanjutan = sum(bool(f[k]) for k in FILTER_LANJUTAN)
        # --- tambahkan sebelum `return {` ---
    qd = request.GET.copy()
    qd.pop('page', None)
    qs_tanpa_page = qd.urlencode()
    qd.pop('sort', None)
    qs_tanpa_sort = qd.urlencode()
    paginator = page_obj.paginator
    page_range = list(paginator.get_elided_page_range(page_obj.number, on_each_side=1, on_ends=1))
    return {
        'kesiswaan': kesiswaan,
        'page_obj': page_obj,
        'item_label': 'prestasi',
        'f': f,
        'sort': sort,
        'sort_toggle': _build_sort_toggle(sort, SORT_KOLOM),
        'statistik': statistik,
        'opsi': opsi,
        'chips': _chip_filter(request, f, opsi ),
        'filter_lanjutan_count': jumlah_lanjutan,
        'buka_filter_lanjutan': bool(jumlah_lanjutan),
        'status_pilihan': [(s, STATUS_LABEL[s]) for s in (status_pilihan or STATUS_LABEL)],
        'tahun_ajaran_aktif': Tahun_ajaran.objects.filter(status='aktif').first(),
        'qs_tanpa_page': qs_tanpa_page,
        'qs_tanpa_sort': qs_tanpa_sort,
        'paginator': paginator,
        'page_range': page_range,
    }


# ==========================================
# DASHBOARD
# ==========================================

@role_required('kesiswaan')
def dashboard(request):
    """Dashboard kesiswaan: ringkasan tahun ajaran aktif, log verifikasi, tabel prestasi."""
    kesiswaan, redirect_response = _guard_kesiswaan(request)
    if redirect_response:
        return redirect_response

    context = _susun_halaman_prestasi(
        request, kesiswaan,
        qs_awal=Prestasi.objects.all(), sort_default='upload_desc',
    )

    # Kartu ringkasan: khusus tahun ajaran aktif (tidak ikut terpengaruh filter tabel)
    tahun_aktif = context['tahun_ajaran_aktif']
    if tahun_aktif:
        prestasi_tahun = Prestasi.objects.filter(tahun_ajaran=tahun_aktif)
        hitung = {r['status']: r['n'] for r in prestasi_tahun.values('status').annotate(n=Count('id'))}
    else:
        hitung = {}

    context.update({
        'active_menu': 'dashboard',
        'tampil_verifikasi': True,
        'tampil_status_filter': True,
        'total_siswa': (
            RiwayatKelas.objects.filter(tahun_ajaran=tahun_aktif).count()
            if tahun_aktif else 0
        ),
        'ringkasan': {s: hitung.get(s, 0) for s in STATUS_LABEL},
        'activity_log': _log_verifikasi_terbaru(3),
    })
    return render(request, 'eprestasi/kesiswaan_portal/dashboard.html', context)

# ==========================================
# LENGKAPI / EDIT PROFIL
# ==========================================

@role_required('kesiswaan')
def lengkapi_profil(request):
    """
    Lengkapi/edit profil kesiswaan. NIP hanya ditampilkan (diisi admin, tidak
    bisa diubah). Yang bisa diisi: nama lengkap, nomor telepon, jabatan.
    """
    kesiswaan = _get_kesiswaan(request)
    if kesiswaan is None:
        messages.error(request, 'Data kesiswaan tidak ditemukan. Hubungi admin.')
        return redirect('logout')

    sudah_lengkap_sebelumnya = kesiswaan.profil_lengkap

    if request.method == 'POST':
        form = KesiswaanProfilForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            kesiswaan.nama = data['nama']
            kesiswaan.no_hp = data['no_hp']
            kesiswaan.jabatan = data['jabatan']
            kesiswaan.save(update_fields=['nama', 'no_hp', 'jabatan'])

            # Nama di sidebar/topbar dibaca dari session.
            request.session['nama'] = kesiswaan.nama

            catat_aktivitas(
                request,
                'akun_diubah',
                'Kesiswaan memperbarui profil' if sudah_lengkap_sebelumnya else 'Kesiswaan melengkapi profil',
                f'NIP {kesiswaan.nip} ({kesiswaan.nama}) menyimpan profilnya.',
                modul='kesiswaan',
            )
            messages.success(request, 'Profil berhasil disimpan.')
            return redirect('kesiswaan_dashboard')
    else:
        form = KesiswaanProfilForm(initial={
            'nama': kesiswaan.nama,
            'no_hp': kesiswaan.no_hp,
            'jabatan': kesiswaan.jabatan,
        })

    context = {
        'form': form,
        'kesiswaan': kesiswaan,
        'active_menu': 'profil',
        'wajib_diisi': not sudah_lengkap_sebelumnya,
    }
    return render(request, 'eprestasi/kesiswaan_portal/lengkapi_profil.html', context)



# ==========================================
# DAFTAR SISWA DENGAN FILTER
# ==========================================

@role_required('kesiswaan')
def daftar_siswa(request):
    """Daftar siswa dengan filter kelas dan nama"""

    kesiswaan, redirect_response = _guard_kesiswaan(request)

    if redirect_response:
        return redirect_response

    siswa_list = (
        Siswa.objects
        .filter(status='aktif')
        .order_by('kelas', 'nama')
    )

    filter_kelas = request.GET.get(
        'kelas',
        ''
    ).strip()

    filter_nama = request.GET.get(
        'nama',
        ''
    ).strip()

    if filter_kelas:
        siswa_list = siswa_list.filter(
            kelas=filter_kelas
        )

    if filter_nama:
        siswa_list = siswa_list.filter(
            nama__icontains=filter_nama
        )

    # Kelas yang dibuat admin untuk tahun ajaran aktif (bukan daftar tetap)
    tahun_aktif = Tahun_ajaran.objects.filter(status='aktif').order_by('-id').first()
    nama_kelas = (
        Kelas.objects.filter(tahun_ajaran=tahun_aktif).order_by('jurusan', 'tingkat', 'nama_kelas')
        .values_list('nama_kelas', flat=True)
        if tahun_aktif else []
    )
    kelas_options = [(n, n) for n in nama_kelas]

    context = {
        'kesiswaan': kesiswaan,
        'siswa_list': siswa_list,
        'kelas_options': kelas_options,
        'active_menu': 'daftar_siswa',
        'filter_kelas': filter_kelas,
        'filter_nama': filter_nama,
        'total_siswa': siswa_list.count(),
    }

    return render(
        request,
        'eprestasi/kesiswaan_portal/daftar_siswa.html',
        context
    )

# ==========================================
# VERIFIKASI LIST (antrean pending)
# ==========================================

@role_required('kesiswaan')
def verifikasi_list(request):
    """Antrean verifikasi: default Pending, status lain lewat tab."""
    kesiswaan, redirect_response = _guard_kesiswaan(request)
    if redirect_response:
        return redirect_response

    context = _susun_halaman_prestasi(
        request, kesiswaan,
        qs_awal=Prestasi.objects.all(),
        sort_default='upload_asc',      # yang paling lama menunggu di atas
        status_default='pending',
    )

    # Status sudah ditampilkan lewat tab, jadi chip status tidak perlu
    context['chips'] = [c for c in context['chips'] if c['key'] != 'status']

    # Link tab: bawa semua filter & sort, kecuali status dan page
    qd = request.GET.copy()
    qd.pop('page', None)
    qd.pop('status', None)

    context.update({
        'active_menu': 'verifikasi',
        'tampil_verifikasi': True,        # status lain butuh kolom & filter verifikasi
        'tampil_status_filter': False,    # diganti tab
        'qs_tanpa_status': qd.urlencode(),
    })
    return render(request, 'eprestasi/kesiswaan_portal/verifikasi_list.html', context)


# ==========================================
# VERIFIKASI DETAIL
# ==========================================

@role_required('kesiswaan')
def verifikasi_detail(request, prestasi_id):
    """
    Detail verifikasi prestasi
    -- 3 keputusan: terima / perbaikan / tolak.
    """

    kesiswaan, redirect_response = _guard_kesiswaan(request)

    if redirect_response:
        return redirect_response

    prestasi = get_object_or_404(
        Prestasi,
        pk=prestasi_id
    )

    NotifikasiDibaca.objects.get_or_create(kesiswaan=kesiswaan, prestasi=prestasi)

    if request.method == 'POST':

        form = VerifikasiPrestasiForm(
            request.POST
        )

        if form.is_valid():

            keputusan = form.cleaned_data[
                'keputusan'
            ]

            # ==========================================
            # DITERIMA
            # ==========================================

            if keputusan == 'diterima':

                prestasi.status = 'diterima'

                prestasi.kesiswaan = kesiswaan

                prestasi.tanggal_verifikasi = (
                    timezone.now()
                )

                prestasi.jenis_perbaikan = None

                prestasi.catatan_perbaikan = None

                prestasi.save()

                NotifikasiSiswa.objects.create(
                    siswa=prestasi.siswa, prestasi=prestasi, status='diterima',
                    pesan=f'Prestasi "{prestasi.nama_prestasi}" diterima.',
                )

                messages.success(
                    request,
                    f'Prestasi "{prestasi.nama_prestasi}" diterima.'
                )

            # ==========================================
            # PERBAIKAN
            # ==========================================

            elif keputusan == 'perbaikan':

                jenis = form.cleaned_data[
                    'jenis_perbaikan'
                ]

                catatan = (
                    form
                    .cleaned_data[
                        'catatan_perbaikan'
                    ]
                    .strip()
                )

                prestasi.status = 'perbaikan'

                prestasi.jenis_perbaikan = jenis

                prestasi.catatan_perbaikan = catatan

                prestasi.kesiswaan = kesiswaan

                prestasi.tanggal_verifikasi = (
                    timezone.now()
                )

                prestasi.save()

                NotifikasiSiswa.objects.create(
                    siswa=prestasi.siswa, prestasi=prestasi, status='perbaikan',
                    pesan=f'Prestasi "{prestasi.nama_prestasi}" perlu perbaikan {"file" if jenis == "file" else "data"}.',
                )

                if jenis == 'file':

                    # File sertifikat lama dihapus
                    # dari Cloudinary.
                    #
                    # Siswa WAJIB unggah ulang
                    # file baru.

                    hapus_sertifikat_prestasi(
                        prestasi
                    )

                    messages.success(
                        request,
                        f'Prestasi "{prestasi.nama_prestasi}" '
                        'dikembalikan untuk perbaikan file. '
                        'File sertifikat lama sudah dihapus '
                        'dari penyimpanan, siswa perlu '
                        'unggah ulang.'
                    )

                else:

                    messages.success(
                        request,
                        f'Prestasi "{prestasi.nama_prestasi}" '
                        'dikembalikan untuk perbaikan data.'
                    )

            # ==========================================
            # DITOLAK
            # ==========================================

            elif keputusan == 'ditolak':

                alasan = (
                    form
                    .cleaned_data[
                        'alasan_penolakan'
                    ]
                    .strip()
                )

                prestasi.status = 'ditolak'

                prestasi.alasan_penolakan = alasan

                prestasi.kesiswaan = kesiswaan

                prestasi.tanggal_verifikasi = (
                    timezone.now()
                )

                prestasi.jenis_perbaikan = None

                prestasi.catatan_perbaikan = None

                prestasi.save()

                NotifikasiSiswa.objects.create(
                    siswa=prestasi.siswa, prestasi=prestasi, status='ditolak',
                    pesan=f'Prestasi "{prestasi.nama_prestasi}" ditolak.',
                )

                # Prestasi ditolak permanen.
                # File sertifikat dihapus dari Cloudinary.

                hapus_sertifikat_prestasi(
                    prestasi
                )

                messages.success(
                    request,
                    f'Prestasi "{prestasi.nama_prestasi}" '
                    'ditolak. File sertifikat sudah '
                    'dihapus dari penyimpanan.'
                )

            return redirect(
                'kesiswaan_verifikasi_list'
            )

        # ==========================================
        # FORM INVALID
        # ==========================================

        context = {
            'prestasi': prestasi,
            'kesiswaan': kesiswaan,
            'form': form,

            'sertifikat_list': (
                prestasi.sertifikat_set.all()
            ),

            'dokumentasi_list': (
                prestasi.dokumentasi_set.all()
            ),

            'active_menu': 'verifikasi',
        }

        return render(
            request,
            'eprestasi/kesiswaan_portal/verifikasi_detail.html',
            context
        )

    # ==========================================
    # GET
    # ==========================================

    context = {
        'prestasi': prestasi,
        'kesiswaan': kesiswaan,
        'form': VerifikasiPrestasiForm(),

        'sertifikat_list': (
            prestasi.sertifikat_set.all()
        ),

        'dokumentasi_list': (
            prestasi.dokumentasi_set.all()
        ),

        'active_menu': 'verifikasi',
    }

    return render(
        request,
        'eprestasi/kesiswaan_portal/verifikasi_detail.html',
        context
    )

# ==========================================
# RIWAYAT VERIFIKASI
# ==========================================

@role_required('kesiswaan')
def riwayat_verifikasi(request):
    """Riwayat prestasi yang sudah diverifikasi (diterima/perbaikan/ditolak)."""
    kesiswaan, redirect_response = _guard_kesiswaan(request)
    if redirect_response:
        return redirect_response

    context = _susun_halaman_prestasi(
        request, kesiswaan,
        qs_awal=Prestasi.objects.filter(status__in=STATUS_TERVERIFIKASI),
        sort_default='verif_desc',
        status_pilihan=list(STATUS_TERVERIFIKASI),
    )
    context.update({
        'active_menu': 'riwayat',
        'tampil_verifikasi': True,
        'tampil_status_filter': True,
    })
    return render(request, 'eprestasi/kesiswaan_portal/riwayat_list.html', context)


# ==========================================
# DATA PRESTASI
# ==========================================

@role_required('kesiswaan')
def data_prestasi(request):
    """Data prestasi per tahun ajaran (default: tahun aktif) + tabel dengan filter/sort/pagination."""
    kesiswaan, redirect_response = _guard_kesiswaan(request)
    if redirect_response:
        return redirect_response

    tahun_aktif = Tahun_ajaran.objects.filter(status='aktif').first()

    context = _susun_halaman_prestasi(
        request, kesiswaan,
        qs_awal=Prestasi.objects.all(),
        sort_default='upload_desc',
        tahun_default=tahun_aktif.id if tahun_aktif else None,
    )
    # Tahun sudah dipilih lewat selector di atas, jadi chip-nya disembunyikan
    context['chips'] = [c for c in context['chips'] if c['key'] != 'tahun']

    tahun_id = context['f']['tahun']
    tahun_terpilih = Tahun_ajaran.objects.filter(id=int(tahun_id)).first() if tahun_id.isdigit() else None

    if tahun_terpilih:
        prestasi_tahun = Prestasi.objects.filter(tahun_ajaran=tahun_terpilih)
        total_siswa = RiwayatKelas.objects.filter(tahun_ajaran=tahun_terpilih).count()
    else:
        prestasi_tahun = Prestasi.objects.all()
        total_siswa = Siswa.objects.filter(status='aktif').count()

    hitung = {r['status']: r['n'] for r in prestasi_tahun.values('status').annotate(n=Count('id'))}
    ringkasan = {s: hitung.get(s, 0) for s in STATUS_LABEL}
    ringkasan['diajukan'] = sum(ringkasan.values())
    ringkasan['persen_diterima'] = (
        round(ringkasan['diterima'] * 100 / ringkasan['diajukan']) if ringkasan['diajukan'] else 0
    )

    qd = request.GET.copy()
    qd.pop('page', None)
    qd.pop('tahun', None)

    context.update({
        'active_menu': 'data_prestasi',
        'tampil_verifikasi': True,
        'tampil_status_filter': True,
        'tahun_terpilih': tahun_terpilih,
        'total_siswa': total_siswa,
        'ringkasan': ringkasan,
        'qs_tanpa_tahun': qd.urlencode(),
    })
    return render(request, 'eprestasi/kesiswaan_portal/data_prestasi.html', context)

@role_required('kesiswaan')
def statistik(request):
    """Statistik prestasi per tahun ajaran (default tahun aktif): kartu, grafik, dan siswa terbaik."""
    kesiswaan, redirect_response = _guard_kesiswaan(request)
    if redirect_response:
        return redirect_response

    tahun_aktif = Tahun_ajaran.objects.filter(status='aktif').first()
    if 'tahun' in request.GET:
        tahun_id = request.GET['tahun'].strip()          # kosong = semua tahun
    else:
        tahun_id = str(tahun_aktif.id) if tahun_aktif else ''
    tahun_terpilih = (
        Tahun_ajaran.objects.filter(id=int(tahun_id)).first() if tahun_id.isdigit() else None
    )

    qs = _anotasi_kelas_riwayat(Prestasi.objects.select_related('siswa'))
    if tahun_terpilih:
        qs = qs.filter(tahun_ajaran=tahun_terpilih)
        total_siswa = RiwayatKelas.objects.filter(tahun_ajaran=tahun_terpilih).count()
    else:
        total_siswa = Siswa.objects.filter(status='aktif').count()
    diterima = qs.filter(status='diterima')

    # ---- Kartu ----
    hitung = {r['status']: r['n'] for r in qs.values('status').annotate(n=Count('id'))}
    ringkasan = {s: hitung.get(s, 0) for s in STATUS_LABEL}
    ringkasan['diajukan'] = sum(ringkasan.values())
    ringkasan['persen_diterima'] = (
        round(ringkasan['diterima'] * 100 / ringkasan['diajukan']) if ringkasan['diajukan'] else 0
    )
    ringkasan['siswa_berprestasi'] = diterima.values('siswa_id').distinct().count()

    # ---- Data grafik ----
    per_tingkat = {r['tingkat_prestasi']: r['n'] for r in diterima.values('tingkat_prestasi').annotate(n=Count('id'))}
    per_kategori = list(diterima.values('kategori_prestasi').annotate(n=Count('id')).order_by('-n'))
    per_jurusan = list(diterima.values('kelas_jurusan').annotate(n=Count('id')).order_by('-n'))
    per_bulan = list(
        qs.annotate(bulan=TruncMonth('tanggal_upload')).values('bulan').annotate(n=Count('id')).order_by('bulan')
    )

    chart_data = {
        'status': {
            'labels': [STATUS_LABEL[s] for s in STATUS_LABEL],
            'data': [ringkasan[s] for s in STATUS_LABEL],
        },
        'tingkat': {
            'labels': [LABEL_TINGKAT[b] for b in sorted(LABEL_TINGKAT)],
            'data': [per_tingkat.get(BOBOT_KE_TINGKAT[b], 0) for b in sorted(LABEL_TINGKAT)],
        },
        'kategori': {
            'labels': [r['kategori_prestasi'].replace('-', ' ').title() for r in per_kategori],
            'data': [r['n'] for r in per_kategori],
        },
        'jurusan': {
            'labels': [r['kelas_jurusan'] or 'Tidak diketahui' for r in per_jurusan],
            'data': [r['n'] for r in per_jurusan],
        },
        'bulan': {
            'labels': [f"{NAMA_BULAN[r['bulan'].month - 1]} {r['bulan'].year}" for r in per_bulan if r['bulan']],
            'data': [r['n'] for r in per_bulan if r['bulan']],
        },
    }

    # ---- Widget siswa terbaik (hanya prestasi yang diterima) ----
    top_jumlah = list(
        diterima.values('siswa_id', 'siswa__nama', 'siswa__nis')
        .annotate(total=Count('id')).order_by('-total', 'siswa__nama')[:5]
    )

    bobot = Case(
        *[When(tingkat_prestasi=k, then=Value(v)) for k, v in BOBOT_TINGKAT.items()],
        default=Value(0), output_field=IntegerField(),
    )
    top_tingkat = list(
        diterima.annotate(bobot=bobot)
        .values('siswa_id', 'siswa__nama', 'siswa__nis')
        .annotate(tertinggi=Max('bobot'), total=Count('id'))
        .order_by('-tertinggi', '-total', 'siswa__nama')[:5]
    )
    for r in top_tingkat:
        r['tingkat_label'] = LABEL_TINGKAT.get(r['tertinggi'], '-')
        contoh = diterima.filter(
            siswa_id=r['siswa_id'], tingkat_prestasi=BOBOT_KE_TINGKAT.get(r['tertinggi'])
        ).order_by('-tanggal_prestasi').first()
        r['contoh'] = contoh.nama_prestasi if contoh else ''

    return render(request, 'eprestasi/kesiswaan_portal/statistik.html', {
        'kesiswaan': kesiswaan,
        'active_menu': 'statistik',
        'tahun_terpilih': tahun_terpilih,
        'tahun_id': tahun_id,
        'tahun_list': list(Tahun_ajaran.objects.order_by('-id')),
        'tahun_ajaran_aktif': tahun_aktif,
        'total_siswa': total_siswa,
        'ringkasan': ringkasan,
        'chart_data': chart_data,
        'top_jumlah': top_jumlah,
        'top_tingkat': top_tingkat,
    })

@role_required('kesiswaan')
def notif_buka(request, prestasi_id):
    """Tandai satu notifikasi sudah dibaca, lalu buka halaman verifikasinya."""
    kesiswaan, redirect_response = _guard_kesiswaan(request)
    if redirect_response:
        return redirect_response

    prestasi = get_object_or_404(Prestasi, pk=prestasi_id)
    NotifikasiDibaca.objects.get_or_create(kesiswaan=kesiswaan, prestasi=prestasi)
    return redirect('kesiswaan_verifikasi_detail', prestasi_id=prestasi.id)


@role_required('kesiswaan')
@require_POST
def notif_tandai_semua(request):
    """Tandai semua notifikasi pending sebagai sudah dibaca."""
    kesiswaan, redirect_response = _guard_kesiswaan(request)
    if redirect_response:
        return redirect_response

    sudah = set(
        NotifikasiDibaca.objects.filter(kesiswaan=kesiswaan).values_list('prestasi_id', flat=True)
    )
    baru = [
        NotifikasiDibaca(kesiswaan=kesiswaan, prestasi_id=pid)
        for pid in Prestasi.objects.filter(status='pending').values_list('id', flat=True)
        if pid not in sudah
    ]
    NotifikasiDibaca.objects.bulk_create(baru, ignore_conflicts=True)

    # Kembali ke halaman asal (dengan pengecekan host supaya aman)
    tujuan = request.META.get('HTTP_REFERER', '')
    if tujuan and url_has_allowed_host_and_scheme(tujuan, allowed_hosts={request.get_host()}):
        return redirect(tujuan)
    return redirect('kesiswaan_dashboard')