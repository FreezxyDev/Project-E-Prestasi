import io

import qrcode
from django.core.files.uploadedfile import InMemoryUploadedFile
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.urls import reverse

from .models import Siswa, Tahun_ajaran, Prestasi
from .forms import SiswaProfilForm
from .decorators import role_required


def _get_siswa(request):
    """Ambil data Siswa milik user yang sedang login (dari session)."""
    return Siswa.objects.filter(users_id=request.session.get('user_id')).first()


@role_required('siswa')
def dashboard(request):
    siswa = _get_siswa(request)
    if siswa is None:
        # Kasus langka: akun Users ber-role siswa tapi baris Siswa-nya hilang/rusak.
        messages.error(request, 'Data siswa tidak ditemukan. Hubungi admin.')
        return redirect('logout')

    # GATE UTAMA: profil belum lengkap -> paksa isi profil dulu, tidak boleh
    # lihat dashboard/upload apa pun sebelum ini terpenuhi.
    if not siswa.profil_lengkap:
        return redirect('siswa_lengkapi_profil')

    context = {
        'siswa': siswa,
        'active_menu': 'dashboard',
        'tahun_ajaran_aktif': Tahun_ajaran.objects.filter(status='aktif').first(),
    }
    return render(request, 'eprestasi/siswa_portal/dashboard.html', context)


@role_required('siswa')
def lengkapi_profil(request):
    siswa = _get_siswa(request)
    if siswa is None:
        messages.error(request, 'Data siswa tidak ditemukan. Hubungi admin.')
        return redirect('logout')

    if request.method == 'POST':
        form = SiswaProfilForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            siswa.nama = data['nama']
            siswa.kelas = data['kelas']
            siswa.jurusan = data['jurusan']
            siswa.email = data.get('email') or None
            siswa.no_hp = data.get('no_hp') or None
            siswa.save()
            messages.success(request, 'Profil berhasil disimpan.')
            return redirect('siswa_dashboard')
    else:
        # Mode edit (profil sudah lengkap, siswa buka halaman ini lagi buat koreksi)
        # -> form diisi otomatis dari data yang sudah ada.
        form = SiswaProfilForm(initial={
            'nama': siswa.nama,
            'kelas': siswa.kelas,
            'jurusan': siswa.jurusan,
            'email': siswa.email,
            'no_hp': siswa.no_hp,
        })

    context = {
        'form': form,
        'siswa': siswa,
        'active_menu': 'profil',
        # Dipakai template buat nentuin boleh/tidaknya tombol "Batal" muncul --
        # kalau profil BELUM pernah lengkap, tidak ada "dashboard" buat dibatalkan ke sana.
        'wajib_diisi': not siswa.profil_lengkap,
    }
    return render(request, 'eprestasi/siswa_portal/lengkapi_profil.html', context)


@role_required('siswa')
def qr_code_view(request):
    """
    QR code menyimpan link ke halaman portofolio PUBLIK siswa (portofolio_publik,
    bisa dibuka siapa saja tanpa login) -- di-generate on-demand lewat tombol
    di sini, BUKAN otomatis pas akun dibuat admin, supaya proses admin bikin
    akun tetap cepat/tidak bergantung ke Cloudinary.
    """
    siswa = _get_siswa(request)
    if siswa is None:
        messages.error(request, 'Data siswa tidak ditemukan. Hubungi admin.')
        return redirect('logout')

    url_portofolio = request.build_absolute_uri(reverse('portofolio_publik', args=[siswa.nis]))

    if request.method == 'POST':
        img = qrcode.make(url_portofolio)
        buffer = io.BytesIO()
        img.save(buffer, format='PNG')
        ukuran = buffer.tell()
        buffer.seek(0)

        # PENTING: CloudinaryField.pre_save() cuma memicu proses upload kalau
        # nilainya instance dari UploadedFile (lihat source cloudinary/models.py).
        # ContentFile BUKAN turunan UploadedFile, jadi kalau dipakai, nilainya
        # nyangkut mentah tanpa pernah di-upload. Makanya wajib pakai
        # InMemoryUploadedFile di sini.
        file_qr = InMemoryUploadedFile(
            buffer, None, f'qr_{siswa.nis}.png', 'image/png', ukuran, None
        )
        siswa.qr_code = file_qr
        siswa.save()

        messages.success(request, 'QR Code berhasil dibuat.')
        return redirect('siswa_qr_code')

    context = {
        'siswa': siswa,
        'active_menu': 'qr',
        'url_portofolio': url_portofolio,
    }
    return render(request, 'eprestasi/siswa_portal/qr_code.html', context)


def portofolio_publik(request, nis):
    """
    Halaman PUBLIK -- sengaja TIDAK pakai @role_required, siapa pun boleh buka
    tanpa login (ini yang di-scan lewat QR code, buat dibagikan ke pihak luar
    misal HRD/panitia PMB). Cuma nampilkan prestasi yang statusnya 'diterima'
    -- yang masih pending/ditolak tidak ditampilkan ke publik.

    Portofolio ini "auto-generate": tidak ada file statis yang disimpan --
    setiap halaman ini dibuka, datanya diambil langsung dari database, jadi
    otomatis ter-update begitu ada prestasi baru yang diverifikasi kesiswaan.
    """
    siswa = get_object_or_404(Siswa, nis=nis)
    prestasi_list = (
        Prestasi.objects
        .filter(siswa=siswa, status='diterima')
        .select_related('kesiswaan', 'tahun_ajaran')
        .prefetch_related('sertifikat_set')
        .order_by('-tanggal_verifikasi')
    )

    context = {
        'siswa': siswa,
        'prestasi_list': prestasi_list,
        'total_prestasi': prestasi_list.count(),
        'total_akademik': prestasi_list.filter(kategori_prestasi='akademik').count(),
        'total_non_akademik': prestasi_list.filter(kategori_prestasi='non-akademik').count(),
        'total_kejuaraan': prestasi_list.filter(kategori_prestasi='kejuaraan').count(),
    }
    return render(request, 'eprestasi/portofolio_publik.html', context)