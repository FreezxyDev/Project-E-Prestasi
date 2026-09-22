from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.utils import timezone

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
                deskripsi=data['deskripsi'],
                kategori_prestasi=data['kategori_prestasi'],
                status='pending',
                # Dokumen Puspresnas -- opsional, cuma keisi kalau siswa
                # benar-benar upload (biasanya prestasi tingkat nasional).
                dokumen_puspresnas=data.get('dokumen_puspresnas') or None,
                jenis_wilayah_puspresnas=data.get('jenis_wilayah_puspresnas') or None,
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

    context = {'form': form, 'active_menu': 'prestasi'}
    return render(request, 'eprestasi/siswa_portal/upload_prestasi.html', context)


@role_required('siswa')
def prestasi_list(request):
    siswa, redirect_response = _guard_siswa(request)
    if redirect_response:
        return redirect_response

    context = {
        'active_menu': 'prestasi',
        'siswa': siswa,
        'prestasi_list': Prestasi.objects.filter(siswa=siswa).order_by('-id'),
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
        'active_menu': 'prestasi',
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
            'penyelenggara': prestasi.penyelenggara,
            'tanggal_prestasi': prestasi.tanggal_prestasi,
            'deskripsi': prestasi.deskripsi,
        })

    context = {
        'active_menu': 'prestasi',
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
