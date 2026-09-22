# KESISWAAN DASHBOARD - MENAMPILKAN VERIFIKASI PRESTASI DENGAN FILTER

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.db.models import Q, Count
from django.utils import timezone
from eprestasi.decorators import role_required
from eprestasi.models import Siswa, Kesiswaan, Prestasi, Tahun_ajaran
from eprestasi.forms import KesiswaanProfilForm, VerifikasiPrestasiForm
from eprestasi.cloudinary_utils import hapus_sertifikat_prestasi

# ==========================================
# HELPER FUNCTIONS
# ==========================================

def _get_kesiswaan(request):
    """Get kesiswaan object dari user yang login"""
    try:
        return Kesiswaan.objects.get(user__username=request.session.get('username'))
    except:
        return None

def _guard_kesiswaan(request):
    """Check jika user sudah lengkap profil"""
    kesiswaan = _get_kesiswaan(request)
    if kesiswaan is None:
        messages.error(request, 'Data kesiswaan tidak ditemukan.')
        return None, redirect('logout')
    
    if not kesiswaan.profil_lengkap:
        messages.warning(request, 'Lengkapi profil Anda dulu.')
        return None, redirect('kesiswaan_lengkapi_profil')
    
    return kesiswaan, None


# ==========================================
# 🆕 MODIFIED DASHBOARD - MENAMPILKAN VERIFIKASI
# ==========================================

@role_required('kesiswaan')
def dashboard(request):
    """
    Dashboard kesiswaan - menampilkan daftar verifikasi prestasi dengan filter
    """
    kesiswaan, redirect_response = _guard_kesiswaan(request)
    if redirect_response:
        return redirect_response

    tahun_ajaran_aktif = Tahun_ajaran.objects.filter(status='aktif').first()

    # Query awal: semua prestasi
    prestasi_list = Prestasi.objects.select_related(
        'siswa', 'tahun_ajaran', 'kesiswaan'
    ).order_by('-tanggal_upload')

    # GET FILTER PARAMETERS
    filter_status = request.GET.get('status', '').strip()
    filter_kategori = request.GET.get('kategori', '').strip()
    filter_tingkat = request.GET.get('tingkat', '').strip()
    filter_kelas = request.GET.get('kelas', '').strip()
    filter_nama = request.GET.get('nama', '').strip()
    filter_tahun = request.GET.get('tahun', '').strip()

    # APPLY FILTERS
    if filter_status:
        prestasi_list = prestasi_list.filter(status=filter_status)

    if filter_kategori:
        prestasi_list = prestasi_list.filter(kategori_prestasi=filter_kategori)

    if filter_tingkat:
        prestasi_list = prestasi_list.filter(tingkat_prestasi=filter_tingkat)

    if filter_kelas:
        prestasi_list = prestasi_list.filter(siswa__kelas=filter_kelas)

    if filter_nama:
        prestasi_list = prestasi_list.filter(siswa__nama__icontains=filter_nama)

    if filter_tahun and tahun_ajaran_aktif:
        prestasi_list = prestasi_list.filter(tahun_ajaran__tahun_ajaran=filter_tahun)

    # STATISTICS
    total_prestasi = prestasi_list.count()
    prestasi_pending = prestasi_list.filter(status='pending').count()
    prestasi_diterima = prestasi_list.filter(status='diterima').count()
    prestasi_perbaikan = prestasi_list.filter(status='perbaikan').count()
    prestasi_ditolak = prestasi_list.filter(status='ditolak').count()

    # GET UNIQUE VALUES UNTUK DROPDOWN FILTER
    tahun_ajaran_list = Tahun_ajaran.objects.all().values_list('tahun_ajaran', flat=True).distinct()
    kategori_choices = Prestasi._meta.get_field('kategori_prestasi').choices
    tingkat_choices = [
        ('Sekolah', 'Sekolah'),
        ('Kota', 'Kota'),
        ('Provinsi', 'Provinsi'),
        ('Nasional', 'Nasional'),
        ('Internasional', 'Internasional'),
    ]
    kelas_options = Siswa.KELAS_CHOICES

    context = {
        'kesiswaan': kesiswaan,
        'prestasi_list': prestasi_list,
        'active_menu': 'dashboard',
        
        # Statistics
        'total_prestasi': total_prestasi,
        'prestasi_pending': prestasi_pending,
        'prestasi_diterima': prestasi_diterima,
        'prestasi_perbaikan': prestasi_perbaikan,
        'prestasi_ditolak': prestasi_ditolak,
        'tahun_ajaran_aktif': tahun_ajaran_aktif,
        
        # Filter options
        'filter_options': {
            'status_choices': [
                ('', '-- Semua Status --'),
                ('pending', '⏳ Pending'),
                ('diterima', '✅ Diterima'),
                ('perbaikan', '🔧 Perbaikan'),
                ('ditolak', '❌ Ditolak'),
            ],
            'kategori_choices': kategori_choices,
            'tingkat_choices': tingkat_choices,
            'kelas_options': kelas_options,
            'tahun_ajaran_list': tahun_ajaran_list,
        },
        
        # Current filter values (untuk maintain di form)
        'current_filters': {
            'status': filter_status,
            'kategori': filter_kategori,
            'tingkat': filter_tingkat,
            'kelas': filter_kelas,
            'nama': filter_nama,
            'tahun': filter_tahun,
        },
    }
    return render(request, 'eprestasi/kesiswaan_portal/dashboard.html', context)


@role_required('kesiswaan')
def lengkapi_profil(request):
    """Lengkapi/edit profil kesiswaan"""
    kesiswaan = _get_kesiswaan(request)
    if kesiswaan is None:
        messages.error(request, 'Data kesiswaan tidak ditemukan. Hubungi admin.')
        return redirect('logout')

    if request.method == 'POST':
        form = KesiswaanProfilForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            kesiswaan.nama = kesiswaan.nama
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


# ==========================================
# DAFTAR SISWA DENGAN FILTER
# ==========================================

@role_required('kesiswaan')
def daftar_siswa(request):
    """Daftar siswa dengan filter kelas dan nama"""
    kesiswaan, redirect_response = _guard_kesiswaan(request)
    if redirect_response:
        return redirect_response

    siswa_list = Siswa.objects.filter(status='aktif').order_by('kelas', 'nama')

    filter_kelas = request.GET.get('kelas', '').strip()
    filter_nama = request.GET.get('nama', '').strip()

    if filter_kelas:
        siswa_list = siswa_list.filter(kelas=filter_kelas)

    if filter_nama:
        siswa_list = siswa_list.filter(nama__icontains=filter_nama)

    kelas_options = Siswa.KELAS_CHOICES

    context = {
        'kesiswaan': kesiswaan,
        'siswa_list': siswa_list,
        'kelas_options': kelas_options,
        'active_menu': 'daftar_siswa',
        'filter_kelas': filter_kelas,
        'filter_nama': filter_nama,
        'total_siswa': siswa_list.count(),
    }
    return render(request, 'eprestasi/kesiswaan_portal/daftar_siswa.html', context)


# ==========================================
# VERIFIKASI LIST
# ==========================================

@role_required('kesiswaan')
def verifikasi_list(request):
    """Daftar prestasi yang perlu diverifikasi"""
    kesiswaan, redirect_response = _guard_kesiswaan(request)
    if redirect_response:
        return redirect_response

    tahun_ajaran_aktif = Tahun_ajaran.objects.filter(status='aktif').first()

    prestasi_list = Prestasi.objects.filter(
        status='pending'
    ).select_related('siswa', 'tahun_ajaran').order_by('-tanggal_upload')

    filter_kelas = request.GET.get('kelas', '').strip()
    filter_nama = request.GET.get('nama', '').strip()

    if filter_kelas:
        prestasi_list = prestasi_list.filter(siswa__kelas=filter_kelas)

    if filter_nama:
        prestasi_list = prestasi_list.filter(siswa__nama__icontains=filter_nama)

    kelas_options = Siswa.KELAS_CHOICES

    context = {
        'kesiswaan': kesiswaan,
        'prestasi_list': prestasi_list,
        'kelas_options': kelas_options,
        'active_menu': 'verifikasi',
        'filter_kelas': filter_kelas,
        'filter_nama': filter_nama,
        'total_prestasi': prestasi_list.count(),
        'tahun_ajaran_aktif': tahun_ajaran_aktif,
    }
    return render(request, 'eprestasi/kesiswaan_portal/verifikasi_list.html', context)


@role_required('kesiswaan')
def verifikasi_detail(request, prestasi_id):
    """Detail verifikasi prestasi -- 3 keputusan: terima / perbaikan / tolak."""
    kesiswaan, redirect_response = _guard_kesiswaan(request)
    if redirect_response:
        return redirect_response

    prestasi = get_object_or_404(Prestasi, pk=prestasi_id)

    if request.method == 'POST':
        form = VerifikasiPrestasiForm(request.POST)

        if form.is_valid():
            keputusan = form.cleaned_data['keputusan']

            if keputusan == 'diterima':
                prestasi.status = 'diterima'
                prestasi.kesiswaan = kesiswaan
                prestasi.tanggal_verifikasi = timezone.now()
                prestasi.jenis_perbaikan = None
                prestasi.catatan_perbaikan = None
                prestasi.save()
                messages.success(request, f'Prestasi "{prestasi.nama_prestasi}" diterima.')

            elif keputusan == 'perbaikan':
                jenis = form.cleaned_data['jenis_perbaikan']
                catatan = form.cleaned_data['catatan_perbaikan'].strip()

                prestasi.status = 'perbaikan'
                prestasi.jenis_perbaikan = jenis
                prestasi.catatan_perbaikan = catatan
                prestasi.kesiswaan = kesiswaan
                prestasi.tanggal_verifikasi = timezone.now()
                prestasi.save()

                if jenis == 'file':
                    # File sertifikat lama dihapus dari Cloudinary -- siswa
                    # WAJIB unggah ulang file baru untuk bisa dikirim lagi.
                    hapus_sertifikat_prestasi(prestasi)
                    messages.success(
                        request,
                        f'Prestasi "{prestasi.nama_prestasi}" dikembalikan untuk perbaikan file. '
                        'File sertifikat lama sudah dihapus dari penyimpanan, siswa perlu unggah ulang.'
                    )
                else:
                    messages.success(
                        request,
                        f'Prestasi "{prestasi.nama_prestasi}" dikembalikan untuk perbaikan data.'
                    )

            elif keputusan == 'ditolak':
                alasan = form.cleaned_data['alasan_penolakan'].strip()

                prestasi.status = 'ditolak'
                prestasi.alasan_penolakan = alasan
                prestasi.kesiswaan = kesiswaan
                prestasi.tanggal_verifikasi = timezone.now()
                prestasi.jenis_perbaikan = None
                prestasi.catatan_perbaikan = None
                prestasi.save()

                # Prestasi ditolak permanen -- file sertifikatnya dihapus dari Cloudinary.
                hapus_sertifikat_prestasi(prestasi)
                messages.success(
                    request,
                    f'Prestasi "{prestasi.nama_prestasi}" ditolak. File sertifikat sudah dihapus dari penyimpanan.'
                )

            return redirect('kesiswaan_verifikasi_list')

        context = {
            'prestasi': prestasi,
            'kesiswaan': kesiswaan,
            'form': form,
            'sertifikat_list': prestasi.sertifikat_set.all(),
            'dokumentasi_list': prestasi.dokumentasi_set.all(),
            'active_menu': 'verifikasi',
        }
        return render(request, 'eprestasi/kesiswaan_portal/verifikasi_detail.html', context)

    context = {
        'prestasi': prestasi,
        'kesiswaan': kesiswaan,
        'form': VerifikasiPrestasiForm(),
        'sertifikat_list': prestasi.sertifikat_set.all(),
        'dokumentasi_list': prestasi.dokumentasi_set.all(),
        'active_menu': 'verifikasi',
    }
    return render(request, 'eprestasi/kesiswaan_portal/verifikasi_detail.html', context)


# ==========================================
# RIWAYAT VERIFIKASI
# ==========================================

@role_required('kesiswaan')
def riwayat_verifikasi(request):
    """Riwayat verifikasi dengan filter"""
    kesiswaan, redirect_response = _guard_kesiswaan(request)
    if redirect_response:
        return redirect_response

    prestasi_list = Prestasi.objects.filter(
        Q(status='diterima') | Q(status='ditolak') | Q(status='perbaikan')
    ).select_related('siswa', 'tahun_ajaran').order_by('-tanggal_verifikasi')

    filter_kelas = request.GET.get('kelas', '').strip()
    filter_nama = request.GET.get('nama', '').strip()
    filter_status = request.GET.get('status', '').strip()

    if filter_kelas:
        prestasi_list = prestasi_list.filter(siswa__kelas=filter_kelas)

    if filter_nama:
        prestasi_list = prestasi_list.filter(siswa__nama__icontains=filter_nama)

    if filter_status in ['diterima', 'ditolak', 'perbaikan']:
        prestasi_list = prestasi_list.filter(status=filter_status)

    kelas_options = Siswa.KELAS_CHOICES
    kelompok_list = _kelompokkan_berdasarkan_tanggal(prestasi_list, 'tanggal_verifikasi')

    context = {
        'kesiswaan': kesiswaan,
        'kelompok_list': kelompok_list,
        'prestasi_list': prestasi_list,
        'kelas_options': kelas_options,
        'active_menu': 'riwayat',
        'filter_kelas': filter_kelas,
        'filter_nama': filter_nama,
        'filter_status': filter_status,
        'total_prestasi': prestasi_list.count(),
    }
    return render(request, 'eprestasi/kesiswaan_portal/riwayat_list.html', context)


def _kelompokkan_berdasarkan_tanggal(queryset, field):
    """Helper: kelompokkan queryset berdasarkan tanggal"""
    from datetime import datetime
    
    kelompok = {}
    for obj in queryset:
        tanggal = getattr(obj, field)
        if tanggal:
            tanggal = tanggal.date()
        else:
            tanggal = datetime.now().date()
        
        if tanggal not in kelompok:
            kelompok[tanggal] = []
        kelompok[tanggal].append(obj)
    
    return sorted(kelompok.items(), key=lambda x: x[0], reverse=True)


@role_required('kesiswaan')
def data_prestasi(request):
    """Statistik dan dashboard data prestasi"""
    kesiswaan, redirect_response = _guard_kesiswaan(request)
    if redirect_response:
        return redirect_response

    tahun_ajaran_aktif = Tahun_ajaran.objects.filter(status='aktif').first()

    if tahun_ajaran_aktif:
        prestasi_all = Prestasi.objects.filter(tahun_ajaran=tahun_ajaran_aktif)
        prestasi_pending = prestasi_all.filter(status='pending').count()
        prestasi_diterima = prestasi_all.filter(status='diterima').count()
        prestasi_perbaikan = prestasi_all.filter(status='perbaikan').count()
        prestasi_ditolak = prestasi_all.filter(status='ditolak').count()
        total_prestasi = prestasi_all.count()
    else:
        prestasi_pending = prestasi_diterima = prestasi_perbaikan = prestasi_ditolak = total_prestasi = 0

    context = {
        'kesiswaan': kesiswaan,
        'active_menu': 'data_prestasi',
        'prestasi_pending': prestasi_pending,
        'prestasi_diterima': prestasi_diterima,
        'prestasi_perbaikan': prestasi_perbaikan,
        'prestasi_ditolak': prestasi_ditolak,
        'total_prestasi': total_prestasi,
        'tahun_ajaran_aktif': tahun_ajaran_aktif,
    }
    return render(request, 'eprestasi/kesiswaan_portal/data_prestasi.html', context)