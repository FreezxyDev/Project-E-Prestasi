import io

import qrcode
from django.contrib.auth.hashers import make_password
from django.core.files.uploadedfile import InMemoryUploadedFile
from django.db.models import Count
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.urls import reverse
from django.views.decorators.http import require_POST

from .models import Siswa, Tahun_ajaran, Prestasi, NotifikasiSiswa, TINGKAT_KE_ROMAWI
from .forms import SiswaProfilForm, SiswaPasswordForm
from .decorators import role_required
from .log_utils import catat_aktivitas


def _get_siswa(request):
    """Ambil data Siswa milik user yang sedang login (dari session)."""
    return Siswa.objects.filter(users_id=request.session.get('user_id')).select_related('users').first()


@role_required('siswa')
def dashboard(request):
    siswa = _get_siswa(request)
    if siswa is None:
        messages.error(request, 'Data siswa tidak ditemukan. Hubungi admin.')
        return redirect('logout')

    # GATE UTAMA: profil belum lengkap -> paksa isi profil dulu.
    if not siswa.profil_lengkap:
        return redirect('siswa_lengkapi_profil')

    semua = Prestasi.objects.filter(siswa=siswa)
    hitung = {r['status']: r['n'] for r in semua.values('status').annotate(n=Count('id'))}
    ringkasan = {s: hitung.get(s, 0) for s in ('pending', 'diterima', 'perbaikan', 'ditolak')}
    ringkasan['total'] = sum(ringkasan.values())

    # Grafik statistik: prestasi DITERIMA per tingkat
    per_tingkat = {r['tingkat_prestasi']: r['n'] for r in semua.filter(status='diterima').values('tingkat_prestasi').annotate(n=Count('id'))}
    urutan = [('sekolah', 'Sekolah'), ('kabupaten/kota', 'Kabupaten/Kota'), ('provinsi', 'Provinsi'), ('nasional', 'Nasional'), ('internasional', 'Internasional')]
    chart_data = {
        'status': {
            'labels': ['Pending', 'Diterima', 'Perbaikan', 'Ditolak'],
            'data': [ringkasan['pending'], ringkasan['diterima'], ringkasan['perbaikan'], ringkasan['ditolak']],
        },
        'tingkat': {
            'labels': [label for _, label in urutan],
            'data': [per_tingkat.get(k, 0) for k, _ in urutan],
        },
    }

    context = {
        'siswa': siswa,
        'active_menu': 'dashboard',
        'tahun_ajaran_aktif': Tahun_ajaran.objects.filter(status='aktif').first(),
        'ringkasan': ringkasan,
        'pengajuan_terbaru': semua.select_related('tahun_ajaran').order_by('-tanggal_upload')[:5],
        'chart_data': chart_data,
        'tingkat_romawi': TINGKAT_KE_ROMAWI.get(siswa.tingkat, siswa.tingkat),
    }
    return render(request, 'eprestasi/siswa_portal/dashboard.html', context)


@role_required('siswa')
def lengkapi_profil(request):
    """
    Halaman Pengaturan siswa.
    - Profil belum lengkap -> form lengkapi profil (email, no. telepon, alamat).
    - Profil lengkap       -> halaman Pengaturan: informasi profil, edit data
                              kontak, QR portofolio, dan ganti password.
    Nama, NIS, kelas, jurusan hanya bisa diubah admin.
    """
    siswa = _get_siswa(request)
    if siswa is None:
        messages.error(request, 'Data siswa tidak ditemukan. Hubungi admin.')
        return redirect('logout')

    sudah_lengkap_sebelumnya = siswa.profil_lengkap
    form = SiswaProfilForm(initial={'email': siswa.email, 'no_hp': siswa.no_hp, 'alamat': siswa.alamat})
    form_password = SiswaPasswordForm(user=siswa.users, siswa=siswa)

    if request.method == 'POST':
        # ---- Ganti password (hanya kalau profil sudah lengkap) ----
        if request.POST.get('aksi') == 'password' and sudah_lengkap_sebelumnya:
            form_password = SiswaPasswordForm(request.POST, user=siswa.users, siswa=siswa)
            if form_password.is_valid():
                user = siswa.users
                user.password = make_password(form_password.cleaned_data['password_baru'])
                user.save(update_fields=['password', 'updated_at'])
                request.session.cycle_key()   # sesi lama tidak bisa dipakai ulang; user tetap login
                catat_aktivitas(
                    request, 'akun_diubah', 'Siswa mengganti password sendiri',
                    f'NIS {siswa.nis} ({siswa.nama}) mengganti passwordnya.', modul='siswa',
                )
                messages.success(request, 'Password berhasil diganti.')
                return redirect('siswa_lengkapi_profil')
            if 'password_lama' in form_password.errors:
                catat_aktivitas(
                    request, 'akun_diubah', 'Percobaan ganti password gagal',
                    f'NIS {siswa.nis} salah memasukkan password saat ini.',
                    modul='siswa', status_log='gagal',
                )

        # ---- Simpan data kontak ----
        else:
            form = SiswaProfilForm(request.POST)
            if form.is_valid():
                data = form.cleaned_data
                # Nama, NIS, kelas, jurusan TIDAK disentuh -- tanggung jawab admin.
                siswa.email = data['email']
                siswa.no_hp = data['no_hp']
                siswa.alamat = data['alamat']
                siswa.save(update_fields=['email', 'no_hp', 'alamat'])
                catat_aktivitas(
                    request, 'akun_diubah',
                    'Siswa memperbarui profil' if sudah_lengkap_sebelumnya else 'Siswa melengkapi profil',
                    f'NIS {siswa.nis} ({siswa.nama}) menyimpan data kontaknya.', modul='siswa',
                )
                messages.success(request, 'Profil berhasil disimpan.')
                return redirect('siswa_dashboard' if not sudah_lengkap_sebelumnya else 'siswa_lengkapi_profil')

    context = {
        'form': form,
        'form_password': form_password,
        'siswa': siswa,
        'active_menu': 'pengaturan',
        'wajib_diisi': not sudah_lengkap_sebelumnya,
        'tingkat_romawi': TINGKAT_KE_ROMAWI.get(siswa.tingkat, siswa.tingkat),
        'url_portofolio': request.build_absolute_uri(reverse('portofolio_publik', args=[siswa.nis])),
    }
    return render(request, 'eprestasi/siswa_portal/lengkapi_profil.html', context)


# ==========================================
# NOTIFIKASI SISWA
# ==========================================

@role_required('siswa')
def notif_buka(request, notif_id):
    """Tandai satu notifikasi dibaca, lalu buka detail prestasinya."""
    siswa = _get_siswa(request)
    if siswa is None:
        return redirect('logout')
    # siswa=siswa mencegah siswa lain membuka notifikasi orang lain lewat tebak ID.
    notif = get_object_or_404(NotifikasiSiswa, pk=notif_id, siswa=siswa)
    if not notif.dibaca:
        notif.dibaca = True
        notif.save(update_fields=['dibaca'])
    return redirect('siswa_prestasi_detail', prestasi_id=notif.prestasi_id)


@role_required('siswa')
@require_POST
def notif_tandai_semua(request):
    siswa = _get_siswa(request)
    if siswa is None:
        return redirect('logout')
    NotifikasiSiswa.objects.filter(siswa=siswa, dibaca=False).update(dibaca=True)

    from django.utils.http import url_has_allowed_host_and_scheme
    tujuan = request.META.get('HTTP_REFERER', '')
    if tujuan and url_has_allowed_host_and_scheme(tujuan, allowed_hosts={request.get_host()}):
        return redirect(tujuan)
    return redirect('siswa_dashboard')


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
        # Kembali ke halaman asal (Pengaturan atau halaman QR sendiri)
        return redirect(request.POST.get('next') == 'profil' and 'siswa_lengkapi_profil' or 'siswa_qr_code')

    context = {
        'siswa': siswa,
        'active_menu': 'pengaturan',
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
        .order_by('-tanggal_prestasi', '-id')
    )

    context = {
        'siswa': siswa,
        'prestasi_list': prestasi_list,
        'total_prestasi': prestasi_list.count(),
        'total_akademik': prestasi_list.filter(kategori_prestasi='akademik').count(),
        'total_non_akademik': prestasi_list.filter(kategori_prestasi='non-akademik').count(),
        'total_nasional_plus': prestasi_list.filter(tingkat_prestasi__in=['nasional', 'internasional']).count(),
    }
    return render(request, 'eprestasi/portofolio_publik.html', context)