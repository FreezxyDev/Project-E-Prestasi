from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.utils import timezone
from django.core.paginator import Paginator
from django.db.models import Q, Count

from .models import Siswa, Tahun_ajaran, Prestasi, Sertifikat, Dokumentasi
from .forms import PrestasiUploadForm, SertifikatTambahanForm, DokumentasiTambahanForm, PrestasiEditForm
from .decorators import role_required


def _get_siswa(request):
    return Siswa.objects.filter(users_id=request.session.get('user_id')).first()


def _guard_siswa(request):
    """
    Kumpulan pengecekan yang berulang di semua view prestasi:
    1. Data siswa harus ada
    2. Profil harus sudah lengkap
    3. Status harus aktif (alumni tidak boleh upload/edit apa pun)
    Return (siswa, redirect_response). Kalau redirect_response bukan None,
    berarti salah satu syarat gagal -> view pemanggil harus langsung return itu.
    """
    siswa = _get_siswa(request)
    if siswa is None:
        messages.error(request, 'Data siswa tidak ditemukan. Hubungi admin.')
        return None, redirect('logout')

    if not siswa.profil_lengkap:
        return siswa, redirect('siswa_lengkapi_profil')

    return siswa, None


@role_required('siswa')
def upload_prestasi(request):
    siswa, redirect_response = _guard_siswa(request)
    if redirect_response:
        return redirect_response

    if not siswa.bisa_edit:
        messages.error(request, 'Kamu sudah berstatus alumni, tidak bisa mengunggah prestasi baru lagi.')
        return redirect('siswa_dashboard')

    tahun_aktif = Tahun_ajaran.objects.filter(status='aktif').first()
    if tahun_aktif is None:
        messages.error(request, 'Belum ada tahun ajaran aktif. Silakan hubungi admin sebelum mengunggah prestasi.')
        return redirect('siswa_dashboard')

    if request.method == 'POST':
        form = PrestasiUploadForm(request.POST, request.FILES)
        if form.is_valid():
            data = form.cleaned_data

            prestasi = Prestasi.objects.create(
                siswa=siswa,
                tahun_ajaran=tahun_aktif,
                nama_prestasi=data['nama_prestasi'],
                tanggal_prestasi=data['tanggal_prestasi'],
                penyelenggara=data['penyelenggara'],
                tingkat_prestasi=data['tingkat_prestasi'],
                wilayah_prestasi=data['wilayah_prestasi'],
                deskripsi=data['deskripsi'],
                kategori_prestasi=data['kategori_prestasi'],
                status='pending',
                # Puspresnas -- kode & dokumen dua-duanya opsional (di semua tingkat),
                # siswa bisa isi salah satu atau dua-duanya.
                kode_puspresnas=data.get('kode_puspresnas') or None,
                dokumen_puspresnas=data.get('dokumen_puspresnas') or None,
                # wilayah dokumen Puspresnas mengikuti wilayah prestasi
                jenis_wilayah_puspresnas=data['wilayah_prestasi'] if data.get('dokumen_puspresnas') else None,
                jenis_penyelenggara_puspresnas=data.get('jenis_penyelenggara_puspresnas') or None,
            )

            # 2 bukti WAJIB, dibuat sekaligus bareng prestasinya.
            Sertifikat.objects.create(
                prestasi=prestasi,
                file=data['file_sertifikat'],
                deskripsi=data.get('deskripsi_sertifikat') or '-',
            )
            Dokumentasi.objects.create(
                prestasi=prestasi,
                foto=data['foto_dokumentasi'],
                caption=data.get('caption_dokumentasi') or None,
            )

            messages.success(request, 'Prestasi berhasil diunggah dan menunggu verifikasi kesiswaan.')
            return redirect('siswa_prestasi_detail', prestasi_id=prestasi.id)
    else:
        form = PrestasiUploadForm()

    context = {'form': form, 'siswa': siswa, 'active_menu': 'pengajuan'}
    return render(request, 'eprestasi/siswa_portal/upload_prestasi.html', context)


RIWAYAT_SORT = {
    'tanggal_desc': ('-tanggal_upload', '-id'), 'tanggal_asc': ('tanggal_upload', 'id'),
    'prestasi_asc': ('nama_prestasi', 'id'), 'prestasi_desc': ('-nama_prestasi', 'id'),
    'tingkat_asc': ('tingkat_prestasi', 'id'), 'tingkat_desc': ('-tingkat_prestasi', 'id'),
    'status_asc': ('status', '-tanggal_upload'), 'status_desc': ('-status', '-tanggal_upload'),
}
RIWAYAT_KOLOM = ['tanggal', 'prestasi', 'tingkat', 'status']
RIWAYAT_PAGE_SIZE = 10
STATUS_PILIHAN = [('pending', 'Pending'), ('diterima', 'Diterima'), ('perbaikan', 'Perbaikan'), ('ditolak', 'Ditolak')]
KATEGORI_PILIHAN = [('akademik', 'Akademik'), ('non-akademik', 'Non-Akademik'), ('kejuaraan', 'Kejuaraan')]
TINGKAT_PILIHAN = [('sekolah', 'Sekolah'), ('kabupaten/kota', 'Kabupaten/Kota'), ('provinsi', 'Provinsi'), ('nasional', 'Nasional'), ('internasional', 'Internasional')]


@role_required('siswa')
def prestasi_list(request):
    """Halaman Riwayat: seluruh pengajuan prestasi siswa dengan filter, sorting, pagination."""
    siswa, redirect_response = _guard_siswa(request)
    if redirect_response:
        return redirect_response

    g = request.GET
    f = {k: g.get(k, '').strip() for k in ('q', 'status', 'kategori', 'tingkat', 'tahun')}
    sort = g.get('sort', 'tanggal_desc')
    if sort not in RIWAYAT_SORT:
        sort = 'tanggal_desc'

    dasar = Prestasi.objects.filter(siswa=siswa).select_related('tahun_ajaran')

    # Kartu ringkasan: ikut filter selain status (sama seperti portal kesiswaan)
    def terapkan(qs, abaikan_status=False):
        if f['q']:
            qs = qs.filter(Q(nama_prestasi__icontains=f['q']) | Q(penyelenggara__icontains=f['q']))
        if f['status'] in dict(STATUS_PILIHAN) and not abaikan_status:
            qs = qs.filter(status=f['status'])
        if f['kategori'] in dict(KATEGORI_PILIHAN):
            qs = qs.filter(kategori_prestasi=f['kategori'])
        if f['tingkat'] in dict(TINGKAT_PILIHAN):
            qs = qs.filter(tingkat_prestasi=f['tingkat'])
        if f['tahun'].isdigit():
            qs = qs.filter(tahun_ajaran_id=int(f['tahun']))
        return qs

    hitung = {r['status']: r['n'] for r in terapkan(dasar, True).values('status').annotate(n=Count('id'))}
    statistik = {s: hitung.get(s, 0) for s, _ in STATUS_PILIHAN}
    statistik['total'] = sum(statistik.values())

    page_obj = Paginator(terapkan(dasar).order_by(*RIWAYAT_SORT[sort]), RIWAYAT_PAGE_SIZE).get_page(g.get('page'))
    page_range = list(page_obj.paginator.get_elided_page_range(page_obj.number, on_each_side=1, on_ends=1))

    qd = g.copy(); qd.pop('page', None)
    qs_tanpa_page = qd.urlencode()
    qd.pop('sort', None)
    qs_tanpa_sort = qd.urlencode()
    qd.pop('status', None)
    # diakhiri '&' supaya template tinggal menambah status=...
    qs_tanpa_status = (qd.urlencode() + '&') if qd else ''

    tahun_list = list(Tahun_ajaran.objects.order_by('-id').values_list('id', 'tahun_ajaran'))
    label = {
        'q': lambda v: f'Cari: "{v}"',
        'status': lambda v: f'Status: {dict(STATUS_PILIHAN).get(v, v)}',
        'kategori': lambda v: f'Kategori: {dict(KATEGORI_PILIHAN).get(v, v)}',
        'tingkat': lambda v: f'Tingkat: {dict(TINGKAT_PILIHAN).get(v, v)}',
        'tahun': lambda v: f'Tahun ajaran: {dict((str(i), t) for i, t in tahun_list).get(v, v)}',
    }
    chips = []
    for k in ('q', 'status', 'kategori', 'tingkat', 'tahun'):
        if f[k]:
            c = g.copy(); c.pop(k, None); c.pop('page', None)
            chips.append({'label': label[k](f[k]), 'hapus_qs': c.urlencode()})

    context = {
        'active_menu': 'riwayat',
        'siswa': siswa,
        'page_obj': page_obj,
        'page_range': page_range,
        'f': f,
        'sort': sort,
        'sort_toggle': {c: (f'{c}_desc' if sort == f'{c}_asc' else f'{c}_asc') for c in RIWAYAT_KOLOM},
        'qs_tanpa_page': qs_tanpa_page,
        'qs_tanpa_sort': qs_tanpa_sort,
        'qs_tanpa_status': qs_tanpa_status,
        'statistik': statistik,
        'chips': chips,
        'filter_count': sum(bool(f[k]) for k in ('kategori', 'tingkat', 'tahun')),
        'status_pilihan': STATUS_PILIHAN,
        'kategori_pilihan': KATEGORI_PILIHAN,
        'tingkat_pilihan': TINGKAT_PILIHAN,
        'tahun_list': tahun_list,
    }
    return render(request, 'eprestasi/siswa_portal/prestasi_list.html', context)


@role_required('siswa')
def prestasi_detail(request, prestasi_id):
    siswa, redirect_response = _guard_siswa(request)
    if redirect_response:
        return redirect_response

    # Wajib punya siswa=siswa -- supaya siswa A tidak bisa buka detail prestasi siswa B
    # sekadar dengan menebak-nebak angka ID di URL.
    prestasi = get_object_or_404(Prestasi, id=prestasi_id, siswa=siswa)

    context = {
        'active_menu': 'riwayat',
        'siswa': siswa,
        'prestasi': prestasi,
        'sertifikat_list': prestasi.sertifikat_set.all(),
        'dokumentasi_list': prestasi.dokumentasi_set.all(),
        'sertifikat_form': SertifikatTambahanForm(),
        'dokumentasi_form': DokumentasiTambahanForm(),
    }
    return render(request, 'eprestasi/siswa_portal/prestasi_detail.html', context)


@role_required('siswa')
def tambah_sertifikat(request, prestasi_id):
    siswa, redirect_response = _guard_siswa(request)
    if redirect_response:
        return redirect_response

    prestasi = get_object_or_404(Prestasi, id=prestasi_id, siswa=siswa)

    # Boleh menambah bukti kalau masih 'pending' ATAU sedang dikembalikan untuk
    # perbaikan FILE. Begitu status lain (diterima/ditolak, atau perbaikan DATA
    # yang tidak butuh file baru), data dikunci -- supaya tidak ada yang
    # menambah bukti setelah hasil verifikasi keluar (jaga integritas proses).
    boleh_upload = (
        prestasi.status == 'pending'
        or (prestasi.status == 'perbaikan' and prestasi.jenis_perbaikan == 'file')
    )
    if not boleh_upload:
        messages.error(request, 'Prestasi ini tidak sedang dalam status yang bisa ditambah bukti.')
        return redirect('siswa_prestasi_detail', prestasi_id=prestasi.id)

    sedang_perbaikan_file = prestasi.status == 'perbaikan' and prestasi.jenis_perbaikan == 'file'

    if request.method == 'POST':
        form = SertifikatTambahanForm(request.POST, request.FILES)
        if form.is_valid():
            Sertifikat.objects.create(
                prestasi=prestasi,
                file=form.cleaned_data['file'],
                deskripsi=form.cleaned_data.get('deskripsi') or '-',
            )

            if sedang_perbaikan_file:
                # File baru sudah masuk -- kembalikan ke antrean verifikasi kesiswaan.
                prestasi.status = 'pending'
                prestasi.jenis_perbaikan = None
                prestasi.catatan_perbaikan = None
                prestasi.save()
                messages.success(
                    request,
                    'Sertifikat baru berhasil diunggah. Prestasi ini sudah dikirim ulang untuk diverifikasi kesiswaan.'
                )
            else:
                messages.success(request, 'Bukti sertifikat berhasil ditambahkan.')
        else:
            messages.error(request, 'Gagal menambah sertifikat, periksa kembali file yang diunggah.')

    return redirect('siswa_prestasi_detail', prestasi_id=prestasi.id)


@role_required('siswa')
def tambah_dokumentasi(request, prestasi_id):
    siswa, redirect_response = _guard_siswa(request)
    if redirect_response:
        return redirect_response

    prestasi = get_object_or_404(Prestasi, id=prestasi_id, siswa=siswa)

    if prestasi.status != 'pending':
        messages.error(request, 'Prestasi ini sudah diverifikasi, tidak bisa menambah dokumentasi lagi.')
        return redirect('siswa_prestasi_detail', prestasi_id=prestasi.id)

    if request.method == 'POST':
        form = DokumentasiTambahanForm(request.POST, request.FILES)
        if form.is_valid():
            Dokumentasi.objects.create(
                prestasi=prestasi,
                foto=form.cleaned_data['foto'],
                caption=form.cleaned_data.get('caption') or None,
            )
            messages.success(request, 'Dokumentasi berhasil ditambahkan.')
        else:
            messages.error(request, 'Gagal menambah dokumentasi, periksa kembali file yang diunggah.')

    return redirect('siswa_prestasi_detail', prestasi_id=prestasi.id)


@role_required('siswa')
def edit_prestasi_data(request, prestasi_id):
    """
    Dipakai siswa memperbaiki DATA prestasi yang dikembalikan kesiswaan dengan
    jenis_perbaikan='data' (nama, kategori, tingkat, penyelenggara, tanggal,
    deskripsi -- TIDAK termasuk file, file sertifikat lama tetap dipakai).
    Begitu disimpan, status otomatis balik ke 'pending' untuk diverifikasi ulang.
    """
    siswa, redirect_response = _guard_siswa(request)
    if redirect_response:
        return redirect_response

    prestasi = get_object_or_404(Prestasi, id=prestasi_id, siswa=siswa)

    if not (prestasi.status == 'perbaikan' and prestasi.jenis_perbaikan == 'data'):
        messages.error(request, 'Prestasi ini tidak sedang dalam status perbaikan data.')
        return redirect('siswa_prestasi_detail', prestasi_id=prestasi.id)

    if request.method == 'POST':
        form = PrestasiEditForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            prestasi.nama_prestasi = data['nama_prestasi']
            prestasi.kategori_prestasi = data['kategori_prestasi']
            prestasi.tingkat_prestasi = data['tingkat_prestasi']
            prestasi.wilayah_prestasi = data['wilayah_prestasi']
            if prestasi.dokumen_puspresnas:
                prestasi.jenis_wilayah_puspresnas = data['wilayah_prestasi']
            prestasi.penyelenggara = data['penyelenggara']
            prestasi.tanggal_prestasi = data['tanggal_prestasi']
            prestasi.deskripsi = data['deskripsi']

            # Data sudah diperbaiki -- kembalikan ke antrean verifikasi kesiswaan.
            prestasi.status = 'pending'
            prestasi.jenis_perbaikan = None
            prestasi.catatan_perbaikan = None
            prestasi.save()

            messages.success(request, 'Data prestasi berhasil diperbarui dan dikirim ulang untuk diverifikasi.')
            return redirect('siswa_prestasi_detail', prestasi_id=prestasi.id)
    else:
        form = PrestasiEditForm(initial={
            'nama_prestasi': prestasi.nama_prestasi,
            'kategori_prestasi': prestasi.kategori_prestasi,
            'tingkat_prestasi': prestasi.tingkat_prestasi,
            'wilayah_prestasi': prestasi.wilayah_prestasi,
            'penyelenggara': prestasi.penyelenggara,
            'tanggal_prestasi': prestasi.tanggal_prestasi,
            'deskripsi': prestasi.deskripsi,
        })

    context = {
        'active_menu': 'riwayat',
        'siswa': siswa,
        'prestasi': prestasi,
        'form': form,
    }
    return render(request, 'eprestasi/siswa_portal/edit_prestasi.html', context)


@role_required('siswa')
def hapus_prestasi(request, prestasi_id):
    siswa, redirect_response = _guard_siswa(request)
    if redirect_response:
        return redirect_response

    prestasi = get_object_or_404(Prestasi, id=prestasi_id, siswa=siswa)

    if prestasi.status != 'pending':
        messages.error(request, 'Prestasi yang sudah diverifikasi tidak bisa dihapus.')
        return redirect('siswa_prestasi_detail', prestasi_id=prestasi.id)

    if request.method == 'POST':
        nama = prestasi.nama_prestasi
        prestasi.delete()  # cascade menghapus Sertifikat & Dokumentasi terkait
        messages.success(request, f'Prestasi "{nama}" telah dihapus.')
        return redirect('siswa_prestasi_list')

    return redirect('siswa_prestasi_detail', prestasi_id=prestasi.id)