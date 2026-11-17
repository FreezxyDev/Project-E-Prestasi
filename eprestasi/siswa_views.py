"""
VIEW KHUSUS SISWA (role: siswa) + alur publik yang dipakai siswa.

Isi:
1. Portal siswa  : dashboard, pengaturan/lengkapi profil, notifikasi, QR code, portofolio publik, panduan
2. Prestasi siswa: ajukan, riwayat, detail, tambah bukti, perbaiki data, hapus
3. Lupa password : alur publik (cari akun -> pilih metode -> verifikasi OTP -> password baru)

Bagian admin ada di admin_views.py, bagian kesiswaan di kesiswaan_views.py.
Validasi input memakai form + aturan terpusat (forms.py / form_fields.py / validasi.py).
"""
import hashlib
import io
from datetime import timedelta

import qrcode
from django.contrib import messages
from django.contrib.auth.hashers import make_password
from django.core.files.uploadedfile import InMemoryUploadedFile
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import otp_utils
from . import validasi as v
from .auth_views import _ip_klien, _catat_gagal, _sisa_kunci, _format_sisa_waktu
from .cloudinary_utils import hapus_semua_file_prestasi
from .decorators import role_required
from .forms import (
    DokumentasiTambahanForm, LupaPasswordBaruForm, LupaPasswordCariForm, OtpForm, PrestasiEditForm,
    PrestasiUploadForm, SertifikatTambahanForm, SiswaPasswordForm, SiswaProfilForm,
    konfigurasi_form_prestasi,
)
from .log_utils import catat_aktivitas
from .models import (
    Users, Siswa, Tahun_ajaran, Prestasi, Sertifikat, Dokumentasi, NotifikasiSiswa, LogAktivitas,
    OtpResetPassword, PermintaanResetPassword, TINGKAT_KE_ROMAWI, TINGKAT_CHOICES,
)
from .prestasi_utils import catat_riwayat
from .view_utils import pesan_error_form


# ======================================================================
# 1. PORTAL SISWA
# ======================================================================

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
    urutan = list(TINGKAT_CHOICES)
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
    form = SiswaProfilForm(initial={
        'email': siswa.email, 'no_hp': siswa.no_hp, 'alamat': siswa.alamat,
        'tempat_lahir': siswa.tempat_lahir, 'tanggal_lahir': siswa.tanggal_lahir,
    })
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
                siswa.tempat_lahir = data['tempat_lahir']
                siswa.tanggal_lahir = data['tanggal_lahir']
                siswa.save(update_fields=['email', 'no_hp', 'alamat', 'tempat_lahir', 'tanggal_lahir'])
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


@role_required('siswa', allow_nonaktif=True)
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
        'total_nasional_plus': prestasi_list.filter(tingkat_prestasi__in=['nasional', 'regional', 'internasional']).count(),
    }
    return render(request, 'eprestasi/siswa_portal/portofolio_publik.html', context)


@role_required('siswa')
def panduan(request):
    """Halaman Panduan penggunaan portal untuk siswa (konten statis)."""
    siswa = _get_siswa(request)
    if siswa is None:
        messages.error(request, 'Data siswa tidak ditemukan. Hubungi admin.')
        return redirect('logout')
    if not siswa.profil_lengkap:
        return redirect('siswa_lengkapi_profil')
    return render(request, 'eprestasi/siswa_portal/panduan.html', {
        'siswa': siswa,
        'active_menu': 'panduan',
    })

# ======================================================================
# 2. PRESTASI SISWA
# ======================================================================

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

            with transaction.atomic():
                prestasi = Prestasi.objects.create(
                    siswa=siswa,
                    tahun_ajaran=tahun_aktif,
                    nama_prestasi=data['nama_prestasi'],
                    tanggal_prestasi=data['tanggal_prestasi'],
                    tanggal_mulai=data.get('tanggal_mulai'),
                    penyelenggara=data['penyelenggara'],
                    tingkat_prestasi=data['tingkat_prestasi'],
                    wilayah_prestasi=data['wilayah_prestasi'],
                    deskripsi=data['deskripsi'],
                    kategori_prestasi=data['kategori_prestasi'],
                    subkategori=data['subkategori'],
                    subkategori_lainnya=data.get('subkategori_lainnya') or '',
                    jenis_perolehan=data['jenis_perolehan'],
                    nomor_sertifikat=(data.get('nomor_sertifikat') or '').strip(),
                    tautan_pendukung=data.get('tautan_pendukung') or '',
                    status='pending',
                    # Puspresnas -- kode & dokumen dua-duanya opsional (di semua tingkat),
                    # siswa bisa isi salah satu atau dua-duanya.
                    kode_puspresnas=data.get('kode_puspresnas') or None,
                    dokumen_puspresnas=data.get('dokumen_puspresnas') or None,
                    # wilayah dokumen Puspresnas mengikuti wilayah prestasi
                    jenis_wilayah_puspresnas=data['wilayah_prestasi'] if data.get('dokumen_puspresnas') else None,
                    jenis_penyelenggara_puspresnas=data.get('jenis_penyelenggara_puspresnas') or None,
                )

                # Bukti: hanya yang benar-benar dilampirkan (minimal satu sudah divalidasi form).
                if data.get('file_sertifikat'):
                    Sertifikat.objects.create(
                        prestasi=prestasi,
                        file=data['file_sertifikat'],
                        deskripsi=data.get('deskripsi_sertifikat') or '-',
                    )
                if data.get('foto_dokumentasi'):
                    Dokumentasi.objects.create(
                        prestasi=prestasi,
                        foto=data['foto_dokumentasi'],
                        caption=data.get('caption_dokumentasi') or None,
                    )

                catat_riwayat(
                    prestasi, 'diajukan', pelaku=siswa.nama or siswa.nis, role='siswa',
                    status_baru='pending', catatan='Pengajuan prestasi oleh siswa.',
                )

            messages.success(request, 'Prestasi berhasil diajukan dan menunggu verifikasi kesiswaan.')
            return redirect('siswa_prestasi_detail', prestasi_id=prestasi.id)
    else:
        form = PrestasiUploadForm()

    context = {'form': form, 'siswa': siswa, 'active_menu': 'pengajuan', **konfigurasi_form_prestasi()}
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


KATEGORI_PILIHAN = [('akademik', 'Akademik'), ('non-akademik', 'Non-Akademik'), ]


TINGKAT_PILIHAN = list(TINGKAT_CHOICES)


@role_required('siswa')
def prestasi_list(request):
    """Halaman Riwayat: seluruh pengajuan prestasi siswa dengan filter, sorting, pagination."""
    siswa, redirect_response = _guard_siswa(request)
    if redirect_response:
        return redirect_response

    g = request.GET
    f = {k: v.rapikan_spasi(g.get(k, ''))[:100] for k in ('q', 'status', 'kategori', 'tingkat', 'tahun')}
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
        if v.ke_int_aman(f['tahun']):   # aman dari input non-angka (tidak error 500)
            qs = qs.filter(tahun_ajaran_id=v.ke_int_aman(f['tahun']))
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
        'q': lambda x: f'Cari: "{x}"',
        'status': lambda x: f'Status: {dict(STATUS_PILIHAN).get(x, x)}',
        'kategori': lambda x: f'Kategori: {dict(KATEGORI_PILIHAN).get(x, x)}',
        'tingkat': lambda x: f'Tingkat: {dict(TINGKAT_PILIHAN).get(x, x)}',
        'tahun': lambda x: f'Tahun ajaran: {dict((str(i), t) for i, t in tahun_list).get(x, x)}',
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
        'riwayat_list': prestasi.riwayat_verifikasi.all(),
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
                catat_riwayat(
                    prestasi, 'diajukan_ulang', pelaku=siswa.nama or siswa.nis, role='siswa',
                    status_sebelum='perbaikan', status_baru='pending',
                    catatan='File bukti diunggah ulang.',
                )
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
            with transaction.atomic():
                prestasi.nama_prestasi = data['nama_prestasi']
                prestasi.kategori_prestasi = data['kategori_prestasi']
                prestasi.subkategori = data['subkategori']
                prestasi.subkategori_lainnya = data.get('subkategori_lainnya') or ''
                prestasi.jenis_perolehan = data['jenis_perolehan']
                prestasi.nomor_sertifikat = (data.get('nomor_sertifikat') or '').strip()
                prestasi.tanggal_mulai = data.get('tanggal_mulai')
                prestasi.tautan_pendukung = data.get('tautan_pendukung') or ''
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
                catat_riwayat(
                    prestasi, 'diajukan_ulang', pelaku=siswa.nama or siswa.nis, role='siswa',
                    status_sebelum='perbaikan', status_baru='pending',
                    catatan='Data prestasi diperbaiki siswa.',
                )

            messages.success(request, 'Data prestasi berhasil diperbarui dan dikirim ulang untuk diverifikasi.')
            return redirect('siswa_prestasi_detail', prestasi_id=prestasi.id)
    else:
        form = PrestasiEditForm(initial={
            'nama_prestasi': prestasi.nama_prestasi,
            'kategori_prestasi': prestasi.kategori_prestasi,
            'subkategori': prestasi.subkategori_id,
            'subkategori_lainnya': prestasi.subkategori_lainnya,
            'jenis_perolehan': prestasi.jenis_perolehan,
            'nomor_sertifikat': prestasi.nomor_sertifikat,
            'tanggal_mulai': prestasi.tanggal_mulai,
            'tautan_pendukung': prestasi.tautan_pendukung,
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
        **konfigurasi_form_prestasi(),
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
        # Hapus file (sertifikat + foto dokumentasi) dari Cloudinary dulu, baru baris
        # prestasi di database -- cascade saja hanya menghapus baris DB, bukan file-nya.
        hapus_semua_file_prestasi(prestasi, simpan_perubahan=False)
        prestasi.delete()
        messages.success(request, f'Prestasi "{nama}" telah dihapus.')
        return redirect('siswa_prestasi_list')

    return redirect('siswa_prestasi_detail', prestasi_id=prestasi.id)

# ======================================================================
# 3. LUPA PASSWORD (PUBLIK)
# ======================================================================

# Kunci session
S_USER = 'lp_user_id'


S_OTP = 'lp_otp_id'


S_VERIFIED_UNTIL = 'lp_verified_until'   # epoch detik; batas waktu mengisi password baru


MASA_FORM_PASSWORD_BARU = timedelta(minutes=10)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------
def _kunci_pencarian(request):
    """Pembatas percobaan cari akun (anti tebak-tebak NIS), terpisah dari kunci login."""
    return hashlib.sha256(f'lupa-password:{_ip_klien(request)}'.encode('utf-8')).hexdigest()


def _bersihkan_session(request):
    for k in (S_USER, S_OTP, S_VERIFIED_UNTIL):
        request.session.pop(k, None)


def _cari_siswa(identitas):
    """Cari siswa lewat username akun atau NIS (sama seperti halaman login)."""
    user = Users.objects.filter(username=identitas, role='siswa').first()
    if user:
        siswa = Siswa.objects.filter(users=user).first()
    else:
        siswa = Siswa.objects.select_related('users').filter(nis=identitas).first()
        user = siswa.users if siswa else None
    if not siswa or not user or user.role != 'siswa':
        return None, None
    return user, siswa


def _akun_boleh_reset(user, siswa):
    """Siswa yang sudah keluar tetap boleh (mereka masih bisa login ke QR Code)."""
    return user.anggota_sekolah_valid or siswa.status == 'keluar'


def _muat_sesi(request):
    """Ambil (user, siswa) dari session; None kalau sesi lupa-password tidak ada."""
    user_id = request.session.get(S_USER)
    if not user_id:
        return None, None
    user = Users.objects.filter(id=user_id, role='siswa').first()
    siswa = Siswa.objects.filter(users=user).first() if user else None
    if not user or not siswa:
        _bersihkan_session(request)
        return None, None
    return user, siswa


def _kontak_siswa(siswa):
    return {
        'email': (siswa.email or '').strip(),
        'hp': (siswa.no_hp or '').strip(),
    }


def _detik_sisa(waktu_akhir):
    return max(0, int((waktu_akhir - timezone.now()).total_seconds()))


def _kirim_otp(user, siswa, kanal):
    """
    Buat OTP baru (yang lama dihanguskan) lalu kirim.
    Return (otp, pesan_error). otp=None kalau gagal.
    """
    kontak = _kontak_siswa(siswa)
    tujuan = kontak['email'] if kanal == 'email' else kontak['hp']
    if not tujuan:
        return None, 'Kontak untuk metode ini belum tersedia di profil kamu.'

    sekarang = timezone.now()
    with transaction.atomic():
        Users.objects.select_for_update().get(pk=user.pk)  # kunci supaya tidak balapan

        terakhir = OtpResetPassword.objects.filter(user=user).order_by('-dibuat_pada').first()
        if terakhir:
            sisa = otp_utils.JEDA_KIRIM_ULANG - (sekarang - terakhir.dibuat_pada)
            if sisa.total_seconds() > 0:
                return None, f'Tunggu {int(sisa.total_seconds()) + 1} detik sebelum meminta kode lagi.'

        sejam = OtpResetPassword.objects.filter(
            user=user, dibuat_pada__gte=sekarang - timedelta(hours=1)
        ).count()
        if sejam >= otp_utils.MAKS_KIRIM_PER_JAM:
            return None, 'Terlalu banyak permintaan kode OTP. Coba lagi dalam 1 jam, atau minta reset lewat admin.'

        OtpResetPassword.objects.filter(user=user, terpakai=False).update(terpakai=True)

        kode = otp_utils.buat_kode()
        otp = OtpResetPassword.objects.create(
            user=user, kanal=kanal, tujuan=tujuan,
            kode_hash=otp_utils.hash_kode(user.id, kode),
            dibuat_pada=sekarang,
            kedaluwarsa_pada=sekarang + otp_utils.MASA_BERLAKU_OTP,
        )

    nama = siswa.nama or siswa.nis
    berhasil = (
        otp_utils.kirim_otp_email(tujuan, kode, nama) if kanal == 'email'
        else otp_utils.kirim_otp_hp(tujuan, kode, nama)
    )
    if not berhasil:
        otp.delete()  # gagal terkirim -> jangan dihitung sebagai pengiriman
        return None, 'Kode OTP gagal dikirim. Coba lagi sebentar lagi atau minta reset lewat admin.'
    return otp, None


# ---------------------------------------------------------------------------
# 1. Cari akun
# ---------------------------------------------------------------------------
def lupa_password(request):
    if request.method == 'POST':
        kunci = _kunci_pencarian(request)
        sisa = _sisa_kunci(kunci)
        if sisa is not None:
            messages.error(
                request,
                f'Terlalu banyak percobaan. Coba lagi dalam {_format_sisa_waktu(sisa)}.'
            )
            return render(request, 'eprestasi/lupa_password/cari_akun.html')

        # Validasi input dulu (wajib diisi, panjang wajar). Isian kosong TIDAK dihitung percobaan gagal.
        form = LupaPasswordCariForm(request.POST)
        if not form.is_valid():
            pesan_error_form(request, form)
            return render(request, 'eprestasi/lupa_password/cari_akun.html')
        identitas = form.cleaned_data['identitas']
        user, siswa = _cari_siswa(identitas)

        if not user:
            _catat_gagal(kunci)
            messages.error(
                request,
                'Akun siswa dengan NIS / username tersebut tidak ditemukan. '
                'Untuk akun kesiswaan atau admin, hubungi administrator.'
            )
            return render(request, 'eprestasi/lupa_password/cari_akun.html', {'identitas': identitas})

        if not _akun_boleh_reset(user, siswa):
            messages.error(
                request,
                'Akun ini tidak terafiliasi dengan SMKN 11 Bandung. Hubungi admin sekolah.'
            )
            return render(request, 'eprestasi/lupa_password/cari_akun.html', {'identitas': identitas})

        _bersihkan_session(request)
        request.session[S_USER] = user.id
        return redirect('lupa_password_metode')

    return render(request, 'eprestasi/lupa_password/cari_akun.html')


# ---------------------------------------------------------------------------
# 2. Pilih metode
# ---------------------------------------------------------------------------
def lupa_password_metode(request):
    user, siswa = _muat_sesi(request)
    if not user:
        return redirect('lupa_password')

    lengkap = siswa.profil_lengkap
    kontak = _kontak_siswa(siswa)
    pending = PermintaanResetPassword.objects.filter(siswa=siswa, status='pending').first()

    if request.method == 'POST':
        aksi = request.POST.get('aksi')

        if aksi == 'admin':
            if not pending:
                pending = PermintaanResetPassword.objects.create(
                    siswa=siswa,
                    alasan='pilih_admin' if lengkap else 'profil_belum_lengkap',
                )
            _bersihkan_session(request)
            return render(request, 'eprestasi/lupa_password/permintaan_terkirim.html', {
                'siswa': siswa, 'permintaan': pending,
            })

        if aksi in ('email', 'hp') and lengkap:
            otp, error = _kirim_otp(user, siswa, aksi)
            if error:
                messages.error(request, error)
            else:
                request.session[S_OTP] = otp.id
                messages.success(
                    request,
                    f'Kode OTP dikirim ke {"email" if aksi == "email" else "nomor HP"} kamu.'
                )
                return redirect('lupa_password_verifikasi')
        elif aksi in ('email', 'hp'):
            messages.error(request, 'Profil kamu belum lengkap, jadi OTP belum bisa dipakai.')

    return render(request, 'eprestasi/lupa_password/pilih_metode.html', {
        'siswa': siswa,
        'lengkap': lengkap,
        'email_samar': otp_utils.samarkan_email(kontak['email']) if kontak['email'] else '',
        'hp_samar': otp_utils.samarkan_hp(kontak['hp']) if kontak['hp'] else '',
        'pending': pending,
    })


# ---------------------------------------------------------------------------
# 3. Verifikasi OTP (+ kirim ulang)
# ---------------------------------------------------------------------------
def lupa_password_verifikasi(request):
    user, siswa = _muat_sesi(request)
    if not user:
        return redirect('lupa_password')

    otp = OtpResetPassword.objects.filter(id=request.session.get(S_OTP), user=user).first()
    if not otp:
        return redirect('lupa_password_metode')

    if request.method == 'POST':
        aksi = request.POST.get('aksi')

        # ---- Kirim ulang ----
        if aksi == 'kirim_ulang':
            baru, error = _kirim_otp(user, siswa, otp.kanal)
            if error:
                messages.error(request, error)
            else:
                request.session[S_OTP] = baru.id
                messages.success(request, 'Kode OTP baru sudah dikirim. Kode sebelumnya tidak berlaku lagi.')
            return redirect('lupa_password_verifikasi')

        # ---- Verifikasi ----
        form_otp = OtpForm(request.POST)
        if not form_otp.is_valid():
            # Format salah (bukan 6 digit) -> pesan jelas, tidak mengurangi jatah percobaan OTP.
            pesan_error_form(request, form_otp)
            return redirect('lupa_password_verifikasi')
        kode = form_otp.cleaned_data['kode']
        with transaction.atomic():
            otp = OtpResetPassword.objects.select_for_update().get(pk=otp.pk)

            if otp.terpakai:
                messages.error(request, 'Kode ini sudah tidak berlaku. Silakan kirim ulang kode OTP.')
            elif otp.kedaluwarsa_pada <= timezone.now():
                messages.error(request, 'Kode OTP sudah kedaluwarsa (berlaku 10 menit). Silakan kirim ulang.')
            elif len(kode) != otp_utils.PANJANG_OTP or not otp_utils.cocok(user.id, kode, otp.kode_hash):
                otp.percobaan_salah += 1
                if otp.percobaan_salah >= otp_utils.MAKS_SALAH_PER_OTP:
                    otp.terpakai = True  # hangus
                    messages.error(request, 'Terlalu banyak salah memasukkan kode. Silakan kirim ulang kode OTP.')
                else:
                    sisa = otp_utils.MAKS_SALAH_PER_OTP - otp.percobaan_salah
                    messages.error(request, f'Kode OTP salah. Sisa percobaan: {sisa}.')
                otp.save(update_fields=['percobaan_salah', 'terpakai'])
            else:
                # Benar -> langsung dihanguskan (sekali pakai).
                otp.terpakai = True
                otp.save(update_fields=['terpakai'])
                request.session[S_VERIFIED_UNTIL] = (timezone.now() + MASA_FORM_PASSWORD_BARU).timestamp()
                request.session.pop(S_OTP, None)
                return redirect('lupa_password_baru')

    sekarang = timezone.now()
    jeda_akhir = otp.dibuat_pada + otp_utils.JEDA_KIRIM_ULANG
    tujuan_samar = (
        otp_utils.samarkan_email(otp.tujuan) if otp.kanal == 'email'
        else otp_utils.samarkan_hp(otp.tujuan)
    )
    return render(request, 'eprestasi/lupa_password/verifikasi_otp.html', {
        'siswa': siswa,
        'otp': otp,
        'tujuan_samar': tujuan_samar,
        'sisa_jeda': _detik_sisa(jeda_akhir) if jeda_akhir > sekarang else 0,
        'sisa_berlaku': 0 if (otp.terpakai or otp.kedaluwarsa_pada <= sekarang) else _detik_sisa(otp.kedaluwarsa_pada),
        'masa_berlaku_menit': int(otp_utils.MASA_BERLAKU_OTP.total_seconds() // 60),
    })


# ---------------------------------------------------------------------------
# 4. Password baru
# ---------------------------------------------------------------------------
def lupa_password_baru(request):
    user, siswa = _muat_sesi(request)
    if not user:
        return redirect('lupa_password')

    batas = request.session.get(S_VERIFIED_UNTIL)
    if not batas or timezone.now().timestamp() > batas:
        _bersihkan_session(request)
        messages.error(request, 'Sesi reset password sudah habis. Silakan ulangi dari awal.')
        return redirect('lupa_password')

    if request.method == 'POST':
        form = LupaPasswordBaruForm(request.POST, user=user, siswa=siswa)
        if form.is_valid():
            user.password = make_password(form.cleaned_data['password_baru'])
            user.save(update_fields=['password', 'updated_at'])

            # Semua OTP lain hangus; permintaan ke admin yang masih menunggu dianggap selesai.
            OtpResetPassword.objects.filter(user=user, terpakai=False).update(terpakai=True)
            PermintaanResetPassword.objects.filter(siswa=siswa, status='pending').update(
                status='selesai', diproses_pada=timezone.now(),
                diproses_oleh=user.username, catatan='Direset sendiri oleh siswa lewat OTP.',
            )
            LogAktivitas.objects.create(
                aksi='password_direset',
                judul='Siswa mereset password lewat OTP',
                deskripsi=f'Siswa "{siswa.nama or siswa.nis}" (NIS {siswa.nis}) mereset password '
                          f'lewat OTP.',
                actor=user.username, role_actor='siswa', modul='siswa',
            )
            _bersihkan_session(request)
            messages.success(request, 'Password berhasil diubah. Silakan login dengan password baru.')
            return redirect('login')
    else:
        form = LupaPasswordBaruForm(user=user, siswa=siswa)

    return render(request, 'eprestasi/lupa_password/password_baru.html', {'form': form, 'siswa': siswa})
