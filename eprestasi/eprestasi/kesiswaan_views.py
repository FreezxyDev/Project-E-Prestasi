import datetime

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.db.models import Q
from django.utils import timezone

from .models import Kesiswaan, Siswa, Tahun_ajaran, Prestasi
from .forms import KesiswaanProfilForm, VerifikasiPrestasiForm
from .decorators import role_required


def _get_kesiswaan(request):
    """Ambil data Kesiswaan milik user yang sedang login (dari session)."""
    return Kesiswaan.objects.filter(user_id=request.session.get('user_id')).first()


def _guard_kesiswaan(request):
    """
    Sama seperti _guard_siswa di siswa_prestasi_views.py: kumpulan pengecekan
    yang berulang di semua view kesiswaan. Return (kesiswaan, redirect_response).
    """
    kesiswaan = _get_kesiswaan(request)
    if kesiswaan is None:
        messages.error(request, 'Data kesiswaan tidak ditemukan. Hubungi admin.')
        return None, redirect('logout')

    if not kesiswaan.profil_lengkap:
        return kesiswaan, redirect('kesiswaan_lengkapi_profil')

    return kesiswaan, None


@role_required('kesiswaan')
def dashboard(request):
    kesiswaan = _get_kesiswaan(request)
    if kesiswaan is None:
        messages.error(request, 'Data kesiswaan tidak ditemukan. Hubungi admin.')
        return redirect('logout')

    # GATE UTAMA: sama seperti siswa -- profil (nama, jabatan) wajib lengkap
    # dulu sebelum bisa masuk ke sistem/dashboard verifikasi.
    if not kesiswaan.profil_lengkap:
        return redirect('kesiswaan_lengkapi_profil')

    tahun_aktif = Tahun_ajaran.objects.filter(status='aktif').first()

    # Semua statistik prestasi dihitung khusus buat TAHUN AJARAN AKTIF saja
    # (bukan sepanjang sejarah sekolah), sesuai yang diminta.
    if tahun_aktif:
        prestasi_tahun_ini = Prestasi.objects.filter(tahun_ajaran=tahun_aktif)
    else:
        prestasi_tahun_ini = Prestasi.objects.none()

    kategori_counts = {
        'kejuaraan': prestasi_tahun_ini.filter(kategori_prestasi='kejuaraan').count(),
        'akademik': prestasi_tahun_ini.filter(kategori_prestasi='akademik').count(),
        'non_akademik': prestasi_tahun_ini.filter(kategori_prestasi='non-akademik').count(),
    }

    context = {
        'kesiswaan': kesiswaan,
        'active_menu': 'dashboard',
        'tahun_ajaran_aktif': tahun_aktif,
        'total_siswa_aktif': Siswa.objects.filter(status='aktif').count(),
        'total_prestasi_tahun_ini': prestasi_tahun_ini.count(),
        'total_pending': prestasi_tahun_ini.filter(status='pending').count(),
        'kategori_counts': kategori_counts,
    }
    return render(request, 'eprestasi/kesiswaan_portal/dashboard.html', context)


@role_required('kesiswaan')
def lengkapi_profil(request):
    kesiswaan = _get_kesiswaan(request)
    if kesiswaan is None:
        messages.error(request, 'Data kesiswaan tidak ditemukan. Hubungi admin.')
        return redirect('logout')

    if request.method == 'POST':
        form = KesiswaanProfilForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            kesiswaan.nama = data['nama']
            kesiswaan.jabatan = data['jabatan']
            kesiswaan.save()
            messages.success(request, 'Profil berhasil disimpan.')
            return redirect('kesiswaan_dashboard')
    else:
        form = KesiswaanProfilForm(initial={
            'nama': kesiswaan.nama,
            'jabatan': kesiswaan.jabatan,
        })

    context = {
        'form': form,
        'kesiswaan': kesiswaan,
        'wajib_diisi': not kesiswaan.profil_lengkap,
    }
    return render(request, 'eprestasi/kesiswaan_portal/lengkapi_profil.html', context)


# =========================================================
# VERIFIKASI PRESTASI
# =========================================================

@role_required('kesiswaan')
def verifikasi_list(request):
    kesiswaan, redirect_response = _guard_kesiswaan(request)
    if redirect_response:
        return redirect_response

    context = {
        'active_menu': 'verifikasi',
        'kesiswaan': kesiswaan,
        # FIFO -- yang paling lama nunggu, tampil paling atas, biar tidak ada
        # yang "kelupaan" nyangkut lama tanpa diverifikasi.
        'antrean': Prestasi.objects.filter(status='pending').select_related('siswa', 'tahun_ajaran').order_by('tanggal_upload'),
    }
    return render(request, 'eprestasi/kesiswaan_portal/verifikasi_list.html', context)


@role_required('kesiswaan')
def verifikasi_detail(request, prestasi_id):
    kesiswaan, redirect_response = _guard_kesiswaan(request)
    if redirect_response:
        return redirect_response

    prestasi = get_object_or_404(Prestasi, id=prestasi_id)

    if request.method == 'POST':
        # Guard penting: kalau prestasi ini sudah keburu diverifikasi staf lain
        # (misal 2 orang kesiswaan buka halaman yang sama bersamaan), jangan
        # sampai diproses dua kali / ketimpa keputusan yang beda.
        if prestasi.status != 'pending':
            messages.error(request, 'Prestasi ini sudah lebih dulu diverifikasi oleh staf lain.')
            return redirect('kesiswaan_verifikasi_list')

        form = VerifikasiPrestasiForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            prestasi.status = data['keputusan']
            prestasi.kesiswaan = kesiswaan
            prestasi.alasan_penolakan = data['alasan_penolakan'] if data['keputusan'] == 'ditolak' else None
            prestasi.tanggal_verifikasi = timezone.now()
            prestasi.save()

            if data['keputusan'] == 'diterima':
                messages.success(request, f'Prestasi "{prestasi.nama_prestasi}" diterima.')
            else:
                messages.success(request, f'Prestasi "{prestasi.nama_prestasi}" ditolak.')

            return redirect('kesiswaan_verifikasi_list')
    else:
        form = VerifikasiPrestasiForm()

    context = {
        'active_menu': 'verifikasi',
        'kesiswaan': kesiswaan,
        'prestasi': prestasi,
        'sertifikat_list': prestasi.sertifikat_set.all(),
        'dokumentasi_list': prestasi.dokumentasi_set.all(),
        'form': form,
    }
    return render(request, 'eprestasi/kesiswaan_portal/verifikasi_detail.html', context)


@role_required('kesiswaan')
def riwayat_verifikasi(request):
    kesiswaan, redirect_response = _guard_kesiswaan(request)
    if redirect_response:
        return redirect_response

    riwayat_qs = Prestasi.objects.exclude(status='pending').select_related('siswa', 'kesiswaan').order_by('-tanggal_verifikasi')

    context = {
        'active_menu': 'riwayat',
        'kesiswaan': kesiswaan,
        # Bukan list biasa lagi -- ini list of (label_tanggal, [daftar_prestasi]),
        # dipakai template buat bikin heading "Hari Ini" / "Kemarin" / dst.
        'kelompok_riwayat': _kelompokkan_berdasarkan_tanggal(riwayat_qs, field='tanggal_verifikasi'),
    }
    return render(request, 'eprestasi/kesiswaan_portal/riwayat_list.html', context)


BULAN_INDONESIA = [
    'Januari', 'Februari', 'Maret', 'April', 'Mei', 'Juni',
    'Juli', 'Agustus', 'September', 'Oktober', 'November', 'Desember',
]


def _kelompokkan_berdasarkan_tanggal(queryset, field):
    """
    Kelompokkan queryset (yang HARUS sudah diurutkan menurun/terbaru-dulu
    berdasarkan `field`) menjadi label kayak "Hari Ini", "Kemarin", atau
    tanggal spesifik ("20 Agustus 2026") buat yang lebih lama dari itu.

    Return: list berisi tuple (label, [list_item]), urutannya ikut urutan
    queryset aslinya (jadi "Hari Ini" otomatis di atas, dst) -- tidak perlu
    di-sort ulang di sini.
    """
    hari_ini = timezone.localdate()
    kemarin = hari_ini - datetime.timedelta(days=1)

    kelompok = {}
    urutan_label = []

    for item in queryset:
        nilai_tanggal = getattr(item, field)
        if nilai_tanggal is None:
            label = 'Tanggal tidak tercatat'
        else:
            tgl = timezone.localtime(nilai_tanggal).date()
            if tgl == hari_ini:
                label = 'Hari Ini'
            elif tgl == kemarin:
                label = 'Kemarin'
            else:
                # Tulis nama bulan manual (bukan strftime('%B')) supaya tidak
                # bergantung pada locale bahasa yang terinstall di server --
                # banyak server/hosting TIDAK punya locale id_ID, dan kalau
                # dipaksa pakai %B, hasilnya jadi bahasa Inggris ("August")
                # atau malah error, bukan "Agustus".
                nama_bulan = BULAN_INDONESIA[tgl.month - 1]
                label = f'{tgl.day} {nama_bulan} {tgl.year}'

        if label not in kelompok:
            kelompok[label] = []
            urutan_label.append(label)
        kelompok[label].append(item)

    return [(label, kelompok[label]) for label in urutan_label]


# =========================================================
# DATA PRESTASI -- halaman filter komprehensif
# =========================================================

# Pilihan tingkat prestasi & kategori disalin dari forms.py (bukan di-import,
# supaya halaman ini tidak ikut kena kalau ada perubahan tak terduga pada
# form upload -- filter halaman ini sengaja berdiri sendiri).
TINGKAT_PRESTASI_PILIHAN = [
    ('sekolah', 'Sekolah'),
    ('kabupaten/kota', 'Kabupaten/Kota'),
    ('provinsi', 'Provinsi'),
    ('nasional', 'Nasional'),
    ('internasional', 'Internasional'),
]
KATEGORI_PRESTASI_PILIHAN = [
    ('akademik', 'Akademik'),
    ('non-akademik', 'Non-Akademik'),
    ('kejuaraan', 'Kejuaraan'),
]
STATUS_PRESTASI_PILIHAN = [
    ('pending', 'Pending'),
    ('diterima', 'Diterima'),
    ('ditolak', 'Ditolak'),
]


@role_required('kesiswaan')
def data_prestasi(request):
    kesiswaan, redirect_response = _guard_kesiswaan(request)
    if redirect_response:
        return redirect_response

    # Ambil semua nilai filter dari URL (?tingkat_siswa=10&kategori=akademik&...)
    # -- sengaja pakai GET (bukan POST) supaya hasil filter bisa di-bookmark/
    # dibagikan link-nya, sama seperti pola filter status di Kelola Siswa.
    f_tingkat_siswa = request.GET.get('tingkat_siswa', '')
    f_tingkat_prestasi = request.GET.get('tingkat_prestasi', '')
    f_tahun_ajaran = request.GET.get('tahun_ajaran', '')
    f_tanggal_dari = request.GET.get('tanggal_dari', '')
    f_tanggal_sampai = request.GET.get('tanggal_sampai', '')
    f_kategori = request.GET.get('kategori', '')
    f_puspresnas = request.GET.get('puspresnas', '')
    f_status = request.GET.get('status', '')

    qs = Prestasi.objects.select_related('siswa', 'tahun_ajaran', 'kesiswaan').all()

    if f_tingkat_siswa:
        qs = qs.filter(siswa__tingkat=f_tingkat_siswa)

    if f_tingkat_prestasi:
        qs = qs.filter(tingkat_prestasi=f_tingkat_prestasi)

    if f_tahun_ajaran:
        qs = qs.filter(tahun_ajaran_id=f_tahun_ajaran)

    if f_tanggal_dari:
        qs = qs.filter(tanggal_prestasi__gte=f_tanggal_dari)

    if f_tanggal_sampai:
        qs = qs.filter(tanggal_prestasi__lte=f_tanggal_sampai)

    if f_kategori:
        qs = qs.filter(kategori_prestasi=f_kategori)

    if f_puspresnas == 'sudah':
        qs = qs.exclude(Q(dokumen_puspresnas__isnull=True) | Q(dokumen_puspresnas=''))
    elif f_puspresnas == 'belum':
        qs = qs.filter(Q(dokumen_puspresnas__isnull=True) | Q(dokumen_puspresnas=''))

    if f_status:
        qs = qs.filter(status=f_status)

    qs = qs.order_by('-tanggal_upload')

    context = {
        'active_menu': 'data_prestasi',
        'kesiswaan': kesiswaan,
        'prestasi_list': qs,
        'total_hasil': qs.count(),
        'tahun_ajaran_semua': Tahun_ajaran.objects.all().order_by('-tahun_ajaran'),
        'tingkat_prestasi_pilihan': TINGKAT_PRESTASI_PILIHAN,
        'kategori_pilihan': KATEGORI_PRESTASI_PILIHAN,
        'status_pilihan': STATUS_PRESTASI_PILIHAN,
        # Dikumpulin dalam 1 dict biar template gampang baca nilai filter yang
        # sedang aktif (buat isi ulang form & bikin opsi <select> "selected").
        'filter': {
            'tingkat_siswa': f_tingkat_siswa,
            'tingkat_prestasi': f_tingkat_prestasi,
            'tahun_ajaran': f_tahun_ajaran,
            'tanggal_dari': f_tanggal_dari,
            'tanggal_sampai': f_tanggal_sampai,
            'kategori': f_kategori,
            'puspresnas': f_puspresnas,
            'status': f_status,
        },
    }
    return render(request, 'eprestasi/kesiswaan_portal/data_prestasi.html', context)
