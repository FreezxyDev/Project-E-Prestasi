"""
VIEW KHUSUS ADMIN (role: admin & super_admin).

Semua fungsi untuk kebutuhan admin dikumpulkan di sini (sebelumnya tersebar di views.py,
siswa_admin_views.py, tahun_ajaran_views.py, views_drilldown.py, kelas_views.py, kelulusan_views.py,
import_views.py, master_views.py, siswa_keluar_views.py, dan sebagian lupa_password_views.py).
Bagian siswa ada di siswa_views.py, bagian kesiswaan ada di kesiswaan_views.py.

Validasi input memakai form + aturan terpusat (forms.py / form_fields.py / validasi.py).
"""
import io
import json
import logging
import re
import secrets
import string
from datetime import timedelta

import openpyxl
from django.contrib import messages
from django.contrib.auth.hashers import make_password
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.core.exceptions import ValidationError
from django.db.models import F, Q, Count, OuterRef, Subquery
from django.db.models.functions import TruncDate
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.utils.http import urlencode
from django.utils.text import slugify
from django.views.decorators.http import require_POST, require_http_methods

from . import validasi as v
from .decorators import role_required
from .forms import (
    PASSWORD_MIN_LENGTH, AdminAkunForm, AdminGantiPasswordForm, BuatKelasMassalForm, CatatanForm, CekNisMassalForm,
    ImportSiswaForm, JurusanBaruForm, KeluarkanSiswaForm, KelasForm, KesiswaanAkunForm, pilihan_jurusan,
    MasterAksiForm, MasterNamaForm, MasterSubkategoriForm, NaikkanOtomatisForm,
    SalinKelasForm, SiswaAkunForm, TahunAjaranForm, TempatkanSiswaForm,
)
from .form_fields import kumpulkan_pesan_error
from .kelas_utils import tahun_ajaran_aktif, tempatkan_ke_kelas, kelas_siswa_aktif
from .log_utils import catat_aktivitas
from .models import (
    Users, Siswa, Kesiswaan, Tahun_ajaran, Prestasi, LogAktivitas, Kelas, RiwayatKelas,
    LogPerubahanKelas, Jurusan, KategoriPrestasi, SubkategoriPrestasi, PermintaanResetPassword, DAFTAR_JURUSAN, DAFTAR_TINGKAT, TINGKAT_KE_ROMAWI, NPSN_SMKN_11_BANDUNG,
)
from .view_utils import (
    PAGE_SIZE, build_sort_toggle, kembali_ke, pengguna_saat_ini, pesan_error_form, ringkas_daftar,
)

_build_sort_toggle = build_sort_toggle   # nama lama dipertahankan di dalam modul


# ======================================================================
# 1. HELPER BERSAMA ADMIN
# ======================================================================


def _generate_username(identifier, bersihkan_akun_sisa=False):
    """
    Username akun dibuat otomatis dari NIS (siswa) / NIP (kesiswaan).

    Kalau username itu sudah dipakai:
    - bersihkan_akun_sisa=True (khusus NIS siswa): akun lama bertipe siswa yang TIDAK punya
      data Siswa sama sekali (sisa dari siswa yang pernah dihapus) dihapus dulu, sehingga username
      tetap bersih tanpa akhiran. Akun yang masih terhubung ke data siswa tidak pernah disentuh.
    - selain itu, tambahkan suffix angka supaya tetap unik (kasus langka, misal re-use NIS/NIP lama).
    """
    if bersihkan_akun_sisa:
        Users.objects.filter(username=identifier, role='siswa', siswa__isnull=True).delete()

    username = identifier
    suffix = 1
    while Users.objects.filter(username=username).exists():
        suffix += 1
        username = f"{identifier}-{suffix}"
    return username


def _naikkan_kelas_siswa_aktif():
    """
    Dipanggil saat tahun ajaran BARU dibuat dan langsung diaktifkan.
    Semua siswa berstatus aktif naik 1 tingkat.
    Siswa yang sudah berada di tingkat 12 otomatis berubah status menjadi alumni
    (dan sejak itu tidak bisa lagi upload sertifikat, lihat Siswa.bisa_edit).

    Memakai 3 query UPDATE massal (bukan menyimpan siswa satu per satu).
    Urutan penting: lulus dulu, lalu naik tingkat 10-11, terakhir tingkat < 10 dinormalkan ke 11.
    """
    aktif = Siswa.objects.filter(status='aktif')
    lulus = aktif.filter(tingkat__gte=12).update(status='alumni')
    naik = aktif.filter(tingkat__gte=10, tingkat__lt=12).update(tingkat=F('tingkat') + 1)
    naik += aktif.filter(tingkat__lt=10).update(tingkat=11)   # data tingkat tidak wajar dinormalkan
    return naik, lulus


# ======================================================================
# 2. DASHBOARD ADMIN
# ======================================================================


@role_required('admin', 'super_admin')
def dashboard(request):
    total_siswa_aktif = Siswa.objects.filter(status='aktif').count()
    total_siswa_alumni = Siswa.objects.filter(status='alumni').count()
    total_kesiswaan = Kesiswaan.objects.count()
    total_prestasi = Prestasi.objects.count()
    pending_verifikasi = Prestasi.objects.filter(status='pending').count()

    total_users = total_siswa_aktif + total_siswa_alumni + total_kesiswaan
    active_users = total_siswa_aktif + total_kesiswaan

    # ---- Aktivitas 7 hari terakhir (upload prestasi per hari) ----
    hari_label = ['Sen', 'Sel', 'Rab', 'Kam', 'Jum', 'Sab', 'Min']
    today = timezone.localdate()
    start = today - timedelta(days=6)
    per_hari = {start + timedelta(days=i): 0 for i in range(7)}
    # Satu query GROUP BY tanggal (sebelumnya semua prestasi 7 hari dibaca satu per satu di Python).
    for baris in (Prestasi.objects.filter(tanggal_upload__date__gte=start)
                  .annotate(tgl=TruncDate('tanggal_upload')).values('tgl').annotate(n=Count('id'))):
        if baris['tgl'] in per_hari:
            per_hari[baris['tgl']] += baris['n']
    aktivitas_labels = [hari_label[d.weekday()] for d in sorted(per_hari.keys())]
    aktivitas_data = [per_hari[d] for d in sorted(per_hari.keys())]

    # ---- Activity log gabungan (upload / verifikasi / akun baru) ----
    activity_log = []

    for p in Prestasi.objects.select_related('siswa').order_by('-tanggal_upload')[:6]:
        activity_log.append({
            'waktu': p.tanggal_upload,
            'judul': 'Prestasi baru diunggah',
            'deskripsi': f'"{p.nama_prestasi}" diunggah oleh {p.siswa.nama or p.siswa.nis}',
            'icon': 'bi-cloud-arrow-up',
            'status': 'pending',
        })

    for p in Prestasi.objects.select_related('siswa').exclude(tanggal_verifikasi=None).order_by('-tanggal_verifikasi')[:6]:
        if p.status == 'diterima':
            activity_log.append({
                'waktu': p.tanggal_verifikasi,
                'judul': 'Prestasi diverifikasi',
                'deskripsi': f'"{p.nama_prestasi}" milik {p.siswa.nama or p.siswa.nis} disetujui',
                'icon': 'bi-patch-check',
                'status': 'success',
            })
        elif p.status == 'ditolak':
            activity_log.append({
                'waktu': p.tanggal_verifikasi,
                'judul': 'Prestasi ditolak',
                'deskripsi': f'"{p.nama_prestasi}" milik {p.siswa.nama or p.siswa.nis} ditolak',
                'icon': 'bi-x-circle',
                'status': 'danger',
            })
        elif p.status == 'perbaikan':
            jenis_label = 'file' if p.jenis_perbaikan == 'file' else 'data'
            activity_log.append({
                'waktu': p.tanggal_verifikasi,
                'judul': 'Prestasi dikembalikan untuk perbaikan',
                'deskripsi': f'"{p.nama_prestasi}" milik {p.siswa.nama or p.siswa.nis} perlu perbaikan {jenis_label}',
                'icon': 'bi-tools',
                'status': 'pending',
            })

    for log in LogAktivitas.objects.order_by('-waktu')[:8]:
        if log.aksi == 'akun_dihapus':
            icon, status = 'bi-person-dash', 'danger'
        else:
            icon, status = 'bi-person-plus', 'success'
        activity_log.append({
            'waktu': log.waktu,
            'judul': log.judul,
            'deskripsi': log.deskripsi,
            'icon': icon,
            'status': status,
        })

    activity_log.sort(key=lambda x: x['waktu'], reverse=True)
    activity_log = activity_log[:8]

    # ---- Recent users (siswa terbaru) ----
    recent_users = (
        Siswa.objects.select_related('users')
        .order_by('-users__created_at')[:6]
    )

    context = {
        'active_menu': 'dashboard',
        'total_siswa_aktif': total_siswa_aktif,
        'total_siswa_alumni': total_siswa_alumni,
        'total_kesiswaan': total_kesiswaan,
        'total_users': total_users,
        'active_users': active_users,
        'pending_verifikasi': pending_verifikasi,
        'total_prestasi': total_prestasi,
        'tahun_ajaran_aktif': Tahun_ajaran.objects.filter(status='aktif').first(),
        'aktivitas_labels': json.dumps(aktivitas_labels),
        'aktivitas_data': json.dumps(aktivitas_data),
        'activity_log': activity_log,
        'recent_users': recent_users,
    }
    return render(request, 'eprestasi/dashboard.html', context)


# ======================================================================
# 3. KELOLA AKUN SISWA
# ======================================================================


SORT_SISWA = {
    'nis_asc': ('nis',), 'nis_desc': ('-nis',),
    'username_asc': ('users__username',), 'username_desc': ('-users__username',),
    'nama_asc': ('nama',), 'nama_desc': ('-nama',),
    'tingkat_asc': ('tingkat', 'kelas', 'nama'), 'tingkat_desc': ('-tingkat', 'kelas', 'nama'),
}


DEFAULT_SORT_SISWA = 'nama_asc'
STATUS_SISWA_VALID = {'aktif', 'nonaktif', 'alumni', 'keluar'}


@role_required('admin', 'super_admin')
def siswa_list(request):
    # Parameter URL dibersihkan & divalidasi: nilai aneh diabaikan (tidak lagi memicu error 500).
    q = v.rapikan_spasi(request.GET.get('q', ''))[:100]
    status_filter = request.GET.get('status', '').strip()
    if status_filter not in STATUS_SISWA_VALID:
        status_filter = ''
    f_kelas = v.rapikan_spasi(request.GET.get('kelas', ''))[:100]
    f_jurusan = request.GET.get('jurusan', '').strip()
    if f_jurusan not in {k for k, _ in pilihan_jurusan()}:
        f_jurusan = ''
    f_tingkat = v.ke_int_aman(request.GET.get('tingkat'), minimal=10, maksimal=12)
    f_tingkat = str(f_tingkat) if f_tingkat else ''
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
        'filter_aktif_count': sum(bool(x) for x in [f_kelas, f_jurusan, f_tingkat]),
        'sort_toggle': _build_sort_toggle(sort, ['nis', 'username', 'nama', 'tingkat']),
        'daftar_kelas': (
            Siswa.objects.exclude(kelas='').exclude(kelas__isnull=True)
            .values_list('kelas', flat=True).distinct().order_by('kelas')
        ),
        'daftar_jurusan': pilihan_jurusan(),
        'daftar_tingkat': DAFTAR_TINGKAT,
        'item_label': 'siswa',  # dipakai partial pagination
        # Statistik: selalu dari seluruh data, tidak ikut terfilter
        'total_semua': Siswa.objects.count(),
        'total_aktif': Siswa.objects.filter(status='aktif').count(),
        'total_tidak_aktif': Siswa.objects.filter(status='nonaktif').count(),
        'total_alumni': Siswa.objects.filter(status='alumni').count(),
        'total_keluar': Siswa.objects.filter(status='keluar').count(),
        'jenis_keluar_choices': Siswa.JENIS_KELUAR_CHOICES,
        'tahun_ajaran_aktif': ta_aktif.tahun_ajaran if ta_aktif else None,
    }
    return render(request, 'eprestasi/siswa/list.html', context)  # sesuaikan path template

@role_required('admin', 'super_admin')
def Create_siswa(request):
    if request.method == 'POST':
        form = SiswaAkunForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            with transaction.atomic():  # Users + profil dibuat bersama atau batal bersama
                username = _generate_username(data['nis'], bersihkan_akun_sisa=True)

                # 1. Simpan Kredensial Login ke Tabel Users
                user_account = Users.objects.create(
                    username=username,
                    password=make_password(data['password']),
                    role='siswa'
                )

                kelas_obj = data['kelas']

                # 2. Simpan Data Diri ke Tabel Siswa (Terhubung via Foreign Key 'users')
                siswa_baru = Siswa.objects.create(
                    users=user_account,
                    nis=data['nis'],
                    nama=data['nama'],
                    jurusan=data.get('jurusan', ''),
                    tingkat=kelas_obj.tingkat,
                    status=data.get('status') or 'aktif',
                )
                # Kelas dicatat per tahun ajaran (RiwayatKelas + log), bukan cuma teks di Siswa.
                tempatkan_ke_kelas(
                    siswa_baru, kelas_obj,
                    pengguna_saat_ini(request),
                )

            catat_aktivitas(
                request, 'akun_dibuat',
                'Admin menambahkan siswa',
                f'Akun siswa "{data["nama"]}" (NIS {data["nis"]}, username {username}) berhasil dibuat',
                modul='siswa',
            )

            messages.success(
                request,
                f'Akun siswa atas nama {data["nama"]} berhasil dibuat. Username login: {username}'
            )
            return redirect('siswa_list')
    else:
        form = SiswaAkunForm()

    context = {'active_menu': 'siswa', 'form': form, 'mode': 'tambah'}
    return render(request, 'eprestasi/siswa/form.html', context)


@role_required('admin', 'super_admin')
def Update_siswa(request, siswa_id):
    siswa = get_object_or_404(Siswa, id=siswa_id)
    user_account = siswa.users

    if request.method == 'POST':
        form = SiswaAkunForm(request.POST, siswa_id=siswa.id, kelas_wajib=(siswa.status == 'aktif'))
        if form.is_valid():
            data = form.cleaned_data

            # 1. Update Password di Tabel Users (jika diisi)
            if data.get('password'):
                user_account.password = make_password(data['password'])
                user_account.save()

            # 2. Update Data Profil di Tabel Siswa
            perubahan = []
            kelas_obj = data.get('kelas')
            if kelas_obj and kelas_obj.nama_kelas != siswa.kelas:
                perubahan.append(f'kelas {siswa.kelas or "-"} → {kelas_obj.nama_kelas}')
            # Status 'keluar' hanya diubah lewat tombol Pulihkan (supaya NPSN ikut dipulihkan).
            status_boleh_diubah = siswa.status != 'keluar'
            if status_boleh_diubah and siswa.status != (data.get('status') or siswa.status):
                perubahan.append(f'status {siswa.status} → {data.get("status")}')

            siswa.nis = data['nis']
            siswa.nama = data['nama']
            siswa.jurusan = data.get('jurusan', '')
            if data.get('status') and status_boleh_diubah:
                siswa.status = data['status']
            siswa.save()

            # Perubahan kelas ditulis ke RiwayatKelas tahun ajaran aktif + log perubahan;
            # Siswa.kelas/tingkat ikut disinkronkan oleh helper.
            if kelas_obj:
                tempatkan_ke_kelas(
                    siswa, kelas_obj,
                    pengguna_saat_ini(request),
                    alasan='Diubah lewat form Edit Siswa',
                )

            catat_aktivitas(
                request, 'akun_diubah',
                'Admin mengubah data siswa',
                f'Data siswa "{siswa.nama}" (NIS {siswa.nis}) diperbarui.' + (
                    ' Perubahan: ' + '; '.join(perubahan) if perubahan else ''
                ),
                modul='siswa',
            )

            messages.success(request, f'Data akun siswa (NIS {siswa.nis}) berhasil diperbarui.')
            return redirect('siswa_list')
    else:
        # Pre-fill data form dari instance Siswa saat ini
        kelas_sekarang = kelas_siswa_aktif(siswa)
        form = SiswaAkunForm(siswa_id=siswa.id, kelas_wajib=(siswa.status == 'aktif'), initial={
            'nis': siswa.nis,
            'nama': siswa.nama,
            'kelas': kelas_sekarang.pk if kelas_sekarang else None,
            'jurusan': siswa.jurusan,
            'status': siswa.status,
        })

    context = {'active_menu': 'siswa', 'form': form, 'mode': 'edit', 'siswa': siswa}
    return render(request, 'eprestasi/siswa/form.html', context)


@role_required('admin', 'super_admin')
def delete_siswa(request, siswa_id):
    siswa = get_object_or_404(Siswa, id=siswa_id)
    if request.method == 'POST':
        nis = siswa.nis
        nama = siswa.nama
        siswa.users.delete()  # cascade menghapus Siswa juga

        catat_aktivitas(
            request, 'akun_dihapus',
            'Admin menghapus siswa',
            f'Akun siswa "{nama}" (NIS {nis}) telah dihapus',
            modul='siswa',
        )

        messages.success(request, f'Akun siswa dengan NIS {nis} telah berhasil dihapus!')
    return redirect('siswa_list')

LABEL_JENIS = dict(Siswa.JENIS_KELUAR_CHOICES)


@role_required('admin', 'super_admin')
@require_POST
def keluarkan_siswa(request, siswa_id):
    siswa = get_object_or_404(Siswa.objects.select_related('users'), id=siswa_id)

    if siswa.status == 'keluar':
        messages.warning(request, f'{siswa.nama or siswa.nis} sudah berstatus keluar.')
        return kembali_ke(request, 'siswa_list')
    if siswa.status == 'alumni':
        messages.error(request, 'Alumni tidak bisa dikeluarkan. Alumni adalah siswa yang sudah lulus.')
        return kembali_ke(request, 'siswa_list')

    form = KeluarkanSiswaForm(request.POST)
    if not form.is_valid():
        pesan_error_form(request, form)
        return kembali_ke(request, 'siswa_list')
    jenis = form.cleaned_data['jenis_keluar']
    tanggal = form.cleaned_data['tanggal_keluar'] or timezone.localdate()
    keterangan = form.cleaned_data['keterangan_keluar']
    status_lama = siswa.status

    with transaction.atomic():
        siswa.status = 'keluar'
        siswa.jenis_keluar = jenis
        siswa.tanggal_keluar = tanggal
        siswa.keterangan_keluar = keterangan
        siswa.save()

        siswa.users.npsn = ''          # cabut afiliasi -> login ditolak
        siswa.users.save(update_fields=['npsn', 'updated_at'])

    catat_aktivitas(
        request, 'siswa_keluar',
        'Admin menandai siswa keluar',
        f'Siswa "{siswa.nama}" (NIS {siswa.nis}) ditandai {LABEL_JENIS[jenis]} per {tanggal:%d-%m-%Y} '
        f'(status sebelumnya: {status_lama}). NPSN akun dicabut; akun menjadi siswa nonaktif.'
        + (f' Keterangan: {keterangan}' if keterangan else ''),
        modul='siswa',
    )
    messages.success(
        request,
        f'{siswa.nama or siswa.nis} ditandai {LABEL_JENIS[jenis].lower()} dan kini menjadi siswa nonaktif: '
        f'masih bisa login hanya untuk melihat portofolio & QR Code, tidak bisa upload prestasi.'
    )
    return kembali_ke(request, 'siswa_list')


@role_required('admin', 'super_admin')
@require_POST
def pulihkan_siswa(request, siswa_id):
    siswa = get_object_or_404(Siswa.objects.select_related('users'), id=siswa_id)

    if siswa.status != 'keluar':
        messages.warning(request, 'Siswa ini tidak berstatus keluar.')
        return kembali_ke(request, 'siswa_list')

    with transaction.atomic():
        siswa.status = 'aktif'
        siswa.jenis_keluar = None
        siswa.tanggal_keluar = None
        siswa.keterangan_keluar = ''
        siswa.save()

        siswa.users.npsn = NPSN_SMKN_11_BANDUNG   # afiliasi dipulihkan
        siswa.users.save(update_fields=['npsn', 'updated_at'])

    catat_aktivitas(
        request, 'siswa_dipulihkan',
        'Admin memulihkan siswa',
        f'Siswa "{siswa.nama}" (NIS {siswa.nis}) dipulihkan ke status aktif. NPSN akun diisi kembali.',
        modul='siswa',
    )
    messages.success(request, f'{siswa.nama or siswa.nis} dipulihkan dan kembali menjadi siswa aktif dengan akses penuh.')
    return kembali_ke(request, 'siswa_list')


# ======================================================================
# 4. KELOLA AKUN KESISWAAN
# ======================================================================


@role_required('admin', 'super_admin')
def kesiswaan_list(request):
    context = {
        'active_menu': 'kesiswaan',
        'kesiswaan_list': Kesiswaan.objects.select_related('user').all().order_by('-id'),
    }
    return render(request, 'eprestasi/kesiswaan/list.html', context)


@role_required('admin', 'super_admin')
def Create_kesiswaan(request):
    if request.method == 'POST':
        form = KesiswaanAkunForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            with transaction.atomic():  # Users + profil dibuat bersama atau batal bersama
                username = _generate_username(data['nip'])

                user_account = Users.objects.create(
                    username=username,
                    password=make_password(data['password']),
                    role='kesiswaan'
                )
                Kesiswaan.objects.create(
                    user=user_account,
                    nip=data['nip'],
                    # nama & jabatan diisi user kesiswaan sendiri setelah login
                )
            catat_aktivitas(
                request, 'akun_dibuat',
                'Admin menambahkan kesiswaan',
                f'Akun kesiswaan (NIP {data["nip"]}, username {username}) berhasil dibuat',
                modul='kesiswaan',
            )

            messages.success(
                request,
                f'Akun kesiswaan berhasil dibuat. Username login: {username} (dapat melengkapi profil setelah login).'
            )
            return redirect('kesiswaan_list')
    else:
        form = KesiswaanAkunForm()

    context = {'active_menu': 'kesiswaan', 'form': form, 'mode': 'tambah'}
    return render(request, 'eprestasi/kesiswaan/form.html', context)


@role_required('admin', 'super_admin')
def Update_kesiswaan(request, kesiswaan_id):
    kesiswaan = get_object_or_404(Kesiswaan, id=kesiswaan_id)
    user_account = kesiswaan.user

    if request.method == 'POST':
        form = KesiswaanAkunForm(request.POST, kesiswaan_id=kesiswaan.id)
        if form.is_valid():
            data = form.cleaned_data

            if data.get('password'):
                user_account.password = make_password(data['password'])
                user_account.save()

            kesiswaan.nip = data['nip']
            kesiswaan.save()

            catat_aktivitas(
                request, 'akun_diubah',
                'Admin mengubah data kesiswaan',
                f'Data akun kesiswaan "{kesiswaan.nama or kesiswaan.nip}" (NIP {kesiswaan.nip}) diperbarui.',
                modul='kesiswaan',
            )

            messages.success(request, f'Data akun kesiswaan (NIP {kesiswaan.nip}) berhasil diperbarui.')
            return redirect('kesiswaan_list')
    else:
        form = KesiswaanAkunForm(kesiswaan_id=kesiswaan.id, initial={'nip': kesiswaan.nip})

    context = {'active_menu': 'kesiswaan', 'form': form, 'mode': 'edit', 'kesiswaan': kesiswaan}
    return render(request, 'eprestasi/kesiswaan/form.html', context)


@role_required('admin', 'super_admin')
def delete_kesiswaan(request, kesiswaan_id):
    kesiswaan = get_object_or_404(Kesiswaan, id=kesiswaan_id)
    if request.method == 'POST':
        nip = kesiswaan.nip
        nama = kesiswaan.nama
        kesiswaan.user.delete()  # cascade menghapus Kesiswaan juga

        catat_aktivitas(
            request, 'akun_dihapus',
            'Admin menghapus kesiswaan',
            f'Akun kesiswaan "{nama or nip}" (NIP {nip}) telah dihapus',
            modul='kesiswaan',
        )

        messages.success(request, f'Akun kesiswaan dengan NIP {nip} telah berhasil dihapus!')
    return redirect('kesiswaan_list')


# ======================================================================
# 5. HAPUS MASSAL
# ======================================================================


def _ids_terpilih(request, pesan_kosong='Pilih minimal satu data terlebih dahulu.', nama='ids'):
    """
    Ambil id dari checkbox (name="ids" atau `nama` lain). Nilai bukan angka ditolak dengan pesan jelas,
    duplikat dibuang. Return list id terurut, atau None kalau tidak valid/kosong (pesan sudah dikirim).
    """
    try:
        ids = v.parse_daftar_id(request.POST.getlist(nama))
    except ValidationError as e:
        messages.error(request, e.messages[0])
        return None
    if not ids:
        messages.error(request, pesan_kosong)
        return None
    return sorted(ids)



@role_required('admin', 'super_admin')
def hapus_massal_siswa(request):
    """Hapus banyak akun siswa sekaligus. Menghapus baris Users -> Siswa, prestasi, riwayat kelas,
    notifikasi, dst. ikut terhapus lewat cascade (sama seperti hapus satu siswa)."""
    if request.method != 'POST':
        return redirect('siswa_list')
    ids = _ids_terpilih(request, 'Pilih minimal satu siswa terlebih dahulu.')
    if ids is None:
        return kembali_ke(request, 'siswa_list')

    terpilih = list(Siswa.objects.filter(id__in=ids).values_list('nis', 'nama', 'users_id'))
    if not terpilih:
        messages.error(request, 'Siswa yang dipilih tidak ditemukan (mungkin sudah dihapus).')
        return kembali_ke(request, 'siswa_list')

    with transaction.atomic():
        Users.objects.filter(id__in=[u for _, _, u in terpilih]).delete()

    daftar = [f'{nama or "-"} ({nis})' for nis, nama, _ in terpilih]
    catat_aktivitas(
        request, 'akun_dihapus', f'Admin menghapus {len(terpilih)} siswa (aksi massal)',
        'Akun siswa dihapus: ' + ringkas_daftar(daftar), modul='siswa',
    )
    messages.success(request, f'{len(terpilih)} akun siswa berhasil dihapus.')
    return kembali_ke(request, 'siswa_list')


@role_required('admin', 'super_admin')
def hapus_massal_kesiswaan(request):
    """Hapus banyak akun kesiswaan sekaligus. Akun milik pengguna yang sedang login dilewati."""
    if request.method != 'POST':
        return redirect('kesiswaan_list')
    ids = _ids_terpilih(request, 'Pilih minimal satu akun kesiswaan terlebih dahulu.')
    if ids is None:
        return kembali_ke(request, 'kesiswaan_list')

    saya = request.session.get('user_id')
    terpilih = [t for t in Kesiswaan.objects.filter(id__in=ids).values_list('nip', 'nama', 'user_id')
                if t[2] != saya]
    if not terpilih:
        messages.error(request, 'Tidak ada akun kesiswaan yang bisa dihapus dari pilihan ini.')
        return kembali_ke(request, 'kesiswaan_list')

    with transaction.atomic():
        Users.objects.filter(id__in=[u for _, _, u in terpilih]).delete()

    daftar = [f'{nama or "-"} (NIP {nip})' for nip, nama, _ in terpilih]
    catat_aktivitas(
        request, 'akun_dihapus', f'Admin menghapus {len(terpilih)} akun kesiswaan (aksi massal)',
        'Akun kesiswaan dihapus: ' + ringkas_daftar(daftar), modul='kesiswaan',
    )
    messages.success(request, f'{len(terpilih)} akun kesiswaan berhasil dihapus.')
    return kembali_ke(request, 'kesiswaan_list')


# ======================================================================
# 6. TAHUN AJARAN
# ======================================================================


SORT_TAHUN_AJARAN = {
    'terbaru': ('-id',), 'terlama': ('id',),
    'nama_asc': ('tahun_ajaran', 'id'), 'nama_desc': ('-tahun_ajaran', '-id'),
    'status_asc': ('status', '-id'), 'status_desc': ('-status', '-id'),
    'siswa_asc': ('jumlah_siswa', '-id'), 'siswa_desc': ('-jumlah_siswa', '-id'),
    'prestasi_asc': ('jumlah_prestasi', '-id'), 'prestasi_desc': ('-jumlah_prestasi', '-id'),
}


DEFAULT_SORT_TAHUN_AJARAN = 'terbaru'


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
    q = v.rapikan_spasi(request.GET.get('q', ''))[:50]
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

@role_required('admin', 'super_admin')
def Create_tahun_ajaran(request):
    if request.method == 'POST':
        form = TahunAjaranForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            jadi_aktif = data['status'] == 'aktif'

            # Atomik: tahun ajaran baru + kenaikan tingkat siswa berhasil bersama atau gagal bersama.
            with transaction.atomic():
                if jadi_aktif:
                    Tahun_ajaran.objects.filter(status='aktif').update(status='nonaktif')

                Tahun_ajaran.objects.create(
                    tahun_ajaran=data['tahun_ajaran'],
                    status=data['status'],
                )
                if jadi_aktif:
                    naik, lulus = _naikkan_kelas_siswa_aktif()

            if jadi_aktif:
                catat_aktivitas(
                    request, 'tahun_ajaran_ditambah',
                    'Admin membuat tahun ajaran baru',
                    f'Tahun ajaran "{data["tahun_ajaran"]}" ditambahkan & diaktifkan. '
                    f'{naik} siswa naik tingkat, {lulus} siswa lulus menjadi alumni.',
                    modul='tahun_ajaran',
                )
                messages.success(
                    request,
                    f'Tahun ajaran {data["tahun_ajaran"]} berhasil ditambahkan dan diaktifkan. '
                    f'{naik} siswa naik tingkat, {lulus} siswa lulus menjadi alumni.'
                )
            else:
                catat_aktivitas(
                    request, 'tahun_ajaran_ditambah',
                    'Admin membuat tahun ajaran baru',
                    f'Tahun ajaran "{data["tahun_ajaran"]}" ditambahkan (nonaktif).',
                    modul='tahun_ajaran',
                )
                messages.success(request, f'Tahun ajaran {data["tahun_ajaran"]} berhasil ditambahkan.')

            return redirect('tahun_ajaran_list')
    else:
        form = TahunAjaranForm(initial={'status': 'nonaktif'})

    context = {'active_menu': 'tahun_ajaran', 'form': form, 'mode': 'tambah'}
    return render(request, 'eprestasi/tahun_ajaran/form.html', context)


@role_required('admin', 'super_admin')
def Update_tahun_ajaran(request, tahun_ajaran_id):
    """
    Mengedit nama/status tahun ajaran yang sudah ada.
    Tidak memicu kenaikan tingkat siswa (lihat catatan pada aktifkan_tahun_ajaran).
    """
    tahun = get_object_or_404(Tahun_ajaran, id=tahun_ajaran_id)

    if request.method == 'POST':
        form = TahunAjaranForm(request.POST, tahun_id=tahun.id)
        if form.is_valid():
            data = form.cleaned_data
            if data['status'] == 'aktif':
                Tahun_ajaran.objects.filter(status='aktif').exclude(id=tahun.id).update(status='nonaktif')
            tahun.tahun_ajaran = data['tahun_ajaran']
            tahun.status = data['status']
            tahun.save()
            catat_aktivitas(
                request, 'tahun_ajaran_diubah',
                'Admin mengubah tahun ajaran',
                f'Tahun ajaran "{tahun.tahun_ajaran}" diperbarui (status: {tahun.status}).',
                modul='tahun_ajaran',
            )
            messages.success(request, f'Tahun ajaran {tahun.tahun_ajaran} berhasil diperbarui.')
            return redirect('tahun_ajaran_list')
    else:
        form = TahunAjaranForm(initial={
            'tahun_ajaran': tahun.tahun_ajaran,
            'status': tahun.status,
        })

    context = {'active_menu': 'tahun_ajaran', 'form': form, 'mode': 'edit', 'tahun': tahun}
    return render(request, 'eprestasi/tahun_ajaran/form.html', context)


@role_required('admin', 'super_admin')
def aktifkan_tahun_ajaran(request, tahun_ajaran_id):
    """
    Mengaktifkan tahun ajaran yang SUDAH ADA (tanpa menaikkan tingkat siswa).
    Kenaikan tingkat hanya terjadi saat tahun ajaran BARU dibuat & langsung diaktifkan
    (lihat Create_tahun_ajaran), supaya siswa tidak naik kelas berkali-kali akibat
    tahun ajaran yang sama diaktif-nonaktifkan berulang.
    """
    tahun = get_object_or_404(Tahun_ajaran, id=tahun_ajaran_id)
    if request.method == 'POST':
        Tahun_ajaran.objects.filter(status='aktif').exclude(id=tahun.id).update(status='nonaktif')
        tahun.status = 'aktif'
        tahun.save()
        catat_aktivitas(
            request, 'tahun_ajaran_diubah', 'Admin mengaktifkan tahun ajaran',
            f'Tahun ajaran "{tahun.tahun_ajaran}" kini aktif.', modul='tahun_ajaran',
        )
        messages.success(request, f'Tahun ajaran {tahun.tahun_ajaran} kini aktif.')
    return redirect('tahun_ajaran_list')


@role_required('admin', 'super_admin')
def nonaktifkan_tahun_ajaran(request, tahun_ajaran_id):
    tahun = get_object_or_404(Tahun_ajaran, id=tahun_ajaran_id)
    if request.method == 'POST':
        tahun.status = 'nonaktif'
        tahun.save()
        catat_aktivitas(
            request, 'tahun_ajaran_diubah', 'Admin menonaktifkan tahun ajaran',
            f'Tahun ajaran "{tahun.tahun_ajaran}" dinonaktifkan.', modul='tahun_ajaran',
        )
        messages.success(request, f'Tahun ajaran {tahun.tahun_ajaran} dinonaktifkan.')
    return redirect('tahun_ajaran_list')


@role_required('admin', 'super_admin')
def delete_tahun_ajaran(request, tahun_ajaran_id):
    tahun = get_object_or_404(Tahun_ajaran, id=tahun_ajaran_id)
    if request.method == 'POST':
        nama = tahun.tahun_ajaran
        tahun.delete()
        catat_aktivitas(
            request, 'akun_dihapus', 'Admin menghapus tahun ajaran',
            f'Tahun ajaran "{nama}" telah dihapus.', modul='tahun_ajaran',
        )
        messages.success(request, f'Tahun ajaran {nama} telah dihapus.')
    return redirect('tahun_ajaran_list')

@role_required('admin', 'super_admin')
def tahun_ajaran_kelas(request, tahun_id):
    """Daftar kelas pada satu tahun ajaran."""
    tahun = get_object_or_404(Tahun_ajaran, pk=tahun_id)
    q = v.rapikan_spasi(request.GET.get('q', ''))[:100]
    tingkat_filter = v.ke_int_aman(request.GET.get('tingkat'), minimal=10, maksimal=12) or ''
    jurusan_filter = request.GET.get('jurusan', '').strip()
    if jurusan_filter not in {k for k, _ in pilihan_jurusan()}:
        jurusan_filter = ''

    # jumlah_siswa di model Kelas adalah @property -> pakai annotate 'jumlah_siswa_hitung'
    kelas_qs = (Kelas.objects.filter(tahun_ajaran=tahun)
                .annotate(jumlah_siswa_hitung=Count('riwayat_kelas', distinct=True))
                .order_by('tingkat', 'jurusan', 'nama_kelas'))

    if q:
        kelas_qs = kelas_qs.filter(nama_kelas__icontains=q)
    if tingkat_filter:
        kelas_qs = kelas_qs.filter(tingkat=tingkat_filter)
    if jurusan_filter:
        kelas_qs = kelas_qs.filter(jurusan=jurusan_filter)

    daftar_kelas = list(kelas_qs)  # tingkat_romawi & jumlah_siswa sudah property di model

    total_kelas = len(daftar_kelas)
    total_siswa = sum(k.jumlah_siswa for k in daftar_kelas)

    # Siswa aktif yang belum ditempatkan ke kelas mana pun pada tahun ajaran ini
    sudah_punya_kelas = RiwayatKelas.objects.filter(tahun_ajaran=tahun).values('siswa_id')
    tanpa_kelas = Siswa.objects.filter(status='aktif').exclude(id__in=sudah_punya_kelas).count()

    return render(request, 'eprestasi/tahun_ajaran/kelas_list.html', {
        'active_menu': 'tahun_ajaran',
        'tahun': tahun,
        'daftar_kelas': daftar_kelas,
        'total_kelas': total_kelas,
        'total_siswa': total_siswa,
        'rata_siswa': round(total_siswa / total_kelas) if total_kelas else 0,
        'maks_siswa': max([k.jumlah_siswa for k in daftar_kelas] + [1]),
        'tanpa_kelas': tanpa_kelas,
        'q': q,
        'tingkat_filter': tingkat_filter,
        'jurusan_filter': jurusan_filter,
        'daftar_tingkat': [(n, TINGKAT_KE_ROMAWI.get(n, n)) for n, _ in DAFTAR_TINGKAT],
        'daftar_jurusan': pilihan_jurusan(),
    })


@role_required('admin', 'super_admin')
def tahun_ajaran_kelas_siswa(request, tahun_id, kelas_id):
    """Daftar siswa pada satu kelas di satu tahun ajaran."""
    tahun = get_object_or_404(Tahun_ajaran, pk=tahun_id)
    kelas = get_object_or_404(Kelas, pk=kelas_id, tahun_ajaran=tahun)
    q = v.rapikan_spasi(request.GET.get('q', ''))[:100]

    semua = Siswa.objects.filter(riwayat_kelas__kelas=kelas).distinct()

    siswa_qs = (semua
                .annotate(jumlah_prestasi=Count('prestasi', distinct=True),
                          jumlah_diterima=Count('prestasi', filter=Q(prestasi__status='diterima'),
                                                distinct=True))
                .order_by('nama', 'nis'))
    if q:
        siswa_qs = siswa_qs.filter(Q(nis__icontains=q) | Q(nama__icontains=q))

    page_obj = Paginator(siswa_qs, 25).get_page(request.GET.get('page'))

    # Total prestasi dihitung untuk SELURUH siswa kelas (bukan hanya halaman ini)
    total = semua.aggregate(
        # Nama alias JANGAN 'prestasi': bentrok dengan relasi Siswa -> prestasi, sehingga
        # 'prestasi__status' dibaca sebagai alias (angka) dan memicu FieldError.
        jml_prestasi=Count('prestasi', distinct=True),
        jml_diterima=Count('prestasi', filter=Q(prestasi__status='diterima'), distinct=True),
    )

    return render(request, 'eprestasi/tahun_ajaran/siswa_kelas.html', {
        'active_menu': 'tahun_ajaran',
        'tahun': tahun,
        'kelas': kelas,
        'page_obj': page_obj,
        'q': q,
        'total_siswa': semua.count(),
        'total_aktif': semua.filter(status='aktif').count(),
        'total_prestasi': total['jml_prestasi'],
        'total_diterima': total['jml_diterima'],
    })


# ======================================================================
# 7. PENGELOLAAN KELAS
# ======================================================================


def _tahun_ajaran_terpilih(request, param='tahun_ajaran'):
    """
    Ambil Tahun_ajaran dari query/POST param (by id). Kalau tidak ada atau
    tidak valid, jatuhkan ke tahun ajaran yang sedang aktif.
    """
    nilai = v.ke_int_aman(request.GET.get(param) or request.POST.get(param))
    tahun = None
    if nilai:
        tahun = Tahun_ajaran.objects.filter(id=nilai).first()
    if not tahun:
        tahun = Tahun_ajaran.objects.filter(status='aktif').first()
    return tahun


def _tahun_ajaran_post_atau_404(request, param='tahun_ajaran'):
    """Tahun ajaran dari POST: id harus angka & terdaftar, kalau tidak -> 404 (bukan error 500)."""
    return get_object_or_404(Tahun_ajaran, id=v.ke_int_aman(request.POST.get(param)) or 0)


def _redirect_kelola_kelas(tahun_ajaran_id):
    return redirect(f"{reverse('kelola_kelas')}?{urlencode({'tahun_ajaran': tahun_ajaran_id})}")


def _redirect_pengelolaan_kelas(tahun_ajaran=None, **extra_params):
    params = {}
    if tahun_ajaran:
        params['tahun_ajaran'] = tahun_ajaran.id
    params.update({k: val for k, val in extra_params.items() if val not in (None, '')})
    query = urlencode(params)   # nilai di-encode dengan benar (spasi, &, dst.)
    url = reverse('pengelolaan_kelas')
    return redirect(f'{url}?{query}' if query else url)


@role_required('admin', 'super_admin')
def pengelolaan_kelas(request):
    tahun_ajaran_terpilih = _tahun_ajaran_terpilih(request)
    daftar_tahun_ajaran = Tahun_ajaran.objects.all().order_by('-id')

    # Parameter URL divalidasi: nilai di luar daftar/bukan angka diabaikan (bukan error 500).
    jurusan_filter = request.GET.get('jurusan', '').strip()
    if jurusan_filter not in {k for k, _ in pilihan_jurusan()}:
        jurusan_filter = ''
    tingkat_filter = v.ke_int_aman(request.GET.get('tingkat'), minimal=10, maksimal=12) or ''
    kelas_filter = request.GET.get('kelas', '').strip()
    if kelas_filter != '__belum__':
        kelas_filter = v.ke_int_aman(kelas_filter) or ''
    q = v.rapikan_spasi(request.GET.get('q', ''))[:100]

    siswa_qs = Siswa.objects.filter(status='aktif').select_related('users')
    if jurusan_filter:
        siswa_qs = siswa_qs.filter(jurusan=jurusan_filter)
    if tingkat_filter:
        siswa_qs = siswa_qs.filter(tingkat=tingkat_filter)
    if q:
        siswa_qs = siswa_qs.filter(Q(nama__icontains=q) | Q(nis__icontains=q))
    siswa_qs = siswa_qs.order_by('nama')

    daftar_kelas_tahun_ini = []
    siswa_rows = []
    jumlah_tanpa_kelas = 0

    if tahun_ajaran_terpilih:
        daftar_kelas_tahun_ini = list(
            Kelas.objects.filter(tahun_ajaran=tahun_ajaran_terpilih)
            .annotate(n_siswa=Count('riwayat_kelas'))
            .order_by('jurusan', 'tingkat', 'nama_kelas')
        )

        riwayat_map = {
            rk.siswa_id: rk
            for rk in RiwayatKelas.objects.filter(
                tahun_ajaran=tahun_ajaran_terpilih, siswa__in=siswa_qs
            ).select_related('kelas')
        }

        for siswa in siswa_qs:
            riwayat = riwayat_map.get(siswa.id)
            # '__belum__' = siswa yang belum punya kelas di tahun ajaran ini.
            # (Sebelumnya cabang ini tidak pernah lolos sehingga tabel selalu kosong.)
            if kelas_filter == '__belum__':
                if riwayat:
                    continue
            elif kelas_filter and (not riwayat or str(riwayat.kelas_id) != str(kelas_filter)):
                continue
            siswa_rows.append({
                'siswa': siswa,
                'riwayat': riwayat,
                'kelas_saat_ini': riwayat.kelas if riwayat else None,
                'tingkat_romawi': TINGKAT_KE_ROMAWI.get(siswa.tingkat, siswa.tingkat),
            })
            if not riwayat:
                jumlah_tanpa_kelas += 1

    context = {
        'active_menu': 'pengelolaan_kelas',
        'daftar_tahun_ajaran': daftar_tahun_ajaran,
        'tahun_ajaran_terpilih': tahun_ajaran_terpilih,
        'daftar_jurusan': pilihan_jurusan(),
        'daftar_tingkat': DAFTAR_TINGKAT,
        'jurusan_filter': jurusan_filter,
        'tingkat_filter': tingkat_filter,
        'kelas_filter': kelas_filter,
        'q': q,
        'daftar_kelas_tahun_ini': daftar_kelas_tahun_ini,
        'siswa_rows': siswa_rows,
        'jumlah_siswa_ditampilkan': len(siswa_rows),
        'jumlah_tanpa_kelas': jumlah_tanpa_kelas,
        'jumlah_kelas': len(daftar_kelas_tahun_ini),
        'form_naik_otomatis': NaikkanOtomatisForm(),
    }
    return render(request, 'eprestasi/pengelolaan_kelas/list.html', context)


@role_required('admin', 'super_admin')
def tempatkan_siswa(request):
    """
    Aksi "Masukkan ke Kelas". Dipakai untuk:
    - Penempatan awal siswa ke kelas.
    - Pembagian ulang kelas X ke XI (bebas dibagi ulang).
    - Perubahan manual kelas XII (WAJIB tombol "Ubah Pembagian Kelas XII"
      diaktifkan lebih dulu di halaman, ditandai lewat field mode_manual_xii).
    """
    if request.method != 'POST':
        return redirect('pengelolaan_kelas')

    filter_balik = {
        'jurusan': v.rapikan_spasi(request.POST.get('balik_jurusan', ''))[:20],
        'tingkat': v.rapikan_spasi(request.POST.get('balik_tingkat', ''))[:5],
        'kelas': v.rapikan_spasi(request.POST.get('balik_kelas', ''))[:20],
        'q': v.rapikan_spasi(request.POST.get('balik_q', ''))[:100],
    }

    # Semua input divalidasi di satu form: tahun ajaran & kelas harus terdaftar, kelas milik
    # tahun ajaran itu, id siswa berupa angka.
    form = TempatkanSiswaForm(request.POST)
    if not form.is_valid():
        pesan_error_form(request, form)
        tahun_balik = Tahun_ajaran.objects.filter(id=v.ke_int_aman(request.POST.get('tahun_ajaran'))).first()
        return _redirect_pengelolaan_kelas(tahun_balik, **filter_balik)

    data = form.cleaned_data
    tahun_ajaran = data['tahun_ajaran']
    kelas_tujuan = data['kelas_tujuan']
    siswa_ids = data['siswa_ids']
    jenis_perubahan = data['jenis_perubahan'] or 'penempatan_awal'
    mode_manual_xii = data['mode_manual_xii']
    alasan_perubahan = data['alasan_perubahan']

    # Aturan #13: perubahan XI ke XII (kelas tingkat 12) hanya boleh lewat
    # aksi ini kalau admin sudah mengaktifkan mode "Ubah Pembagian Kelas XII".
    if kelas_tujuan.tingkat == 12 and not mode_manual_xii:
        messages.error(
            request,
            'Aktifkan dulu tombol "Ubah Pembagian Kelas XII" sebelum memindahkan siswa ke kelas XII secara manual.'
        )
        return _redirect_pengelolaan_kelas(tahun_ajaran, **filter_balik)

    if mode_manual_xii and kelas_tujuan.tingkat == 12:
        jenis_perubahan = 'perubahan_manual'

    admin_user = pengguna_saat_ini(request)
    berhasil = 0
    sudah_di_kelas = 0
    ditolak = []

    # Ambil semua siswa & riwayat sekaligus (2 query), bukan 2 query per siswa.
    siswa_map = {s.id: s for s in Siswa.objects.filter(id__in=siswa_ids, status='aktif')}
    riwayat_map = {
        r.siswa_id: r
        for r in RiwayatKelas.objects.filter(siswa_id__in=siswa_map.keys(), tahun_ajaran=tahun_ajaran).select_related('kelas')
    }

    for sid in siswa_ids:
        siswa = siswa_map.get(sid)
        if not siswa:
            continue

        # Aturan #2-7 & #17: jurusan siswa harus sama dengan jurusan kelas tujuan.
        if siswa.jurusan != kelas_tujuan.jurusan:
            ditolak.append(f'{siswa.nama} (jurusan {siswa.jurusan or "-"})')
            continue

        riwayat_lama = riwayat_map.get(siswa.id)
        kelas_sebelumnya = riwayat_lama.kelas if riwayat_lama else None

        # Sudah di kelas tujuan: tidak ada yang berubah, jangan buat log palsu.
        if riwayat_lama and riwayat_lama.kelas_id == kelas_tujuan.id:
            sudah_di_kelas += 1
            continue

        # Aturan #18: unique_together (siswa, tahun_ajaran) pada RiwayatKelas
        # mencegah penempatan ganda -- update_or_create hanya akan
        # memperbarui baris tahun ajaran yang SEDANG BERJALAN ini,
        # baris tahun ajaran sebelumnya tidak pernah tersentuh.
        RiwayatKelas.objects.update_or_create(
            siswa=siswa, tahun_ajaran=tahun_ajaran,
            defaults={
                'kelas': kelas_tujuan,
                'tingkat': kelas_tujuan.tingkat,
                'tanggal_penempatan': timezone.now(),
                'diubah_oleh': admin_user,
            }
        )
        LogPerubahanKelas.objects.create(
            siswa=siswa,
            kelas_sebelumnya=kelas_sebelumnya,
            kelas_baru=kelas_tujuan,
            tahun_ajaran=tahun_ajaran,
            jenis_perubahan=jenis_perubahan,
            alasan_perubahan=alasan_perubahan or None,
            diubah_oleh=admin_user,
        )

        # Sinkronkan field lama di Siswa supaya fitur lain (daftar siswa,
        # portofolio publik, dsb) tetap tampil konsisten -- hanya kalau
        # tahun ajaran yang sedang diproses adalah tahun ajaran AKTIF.
        if tahun_ajaran.status == 'aktif':
            siswa.kelas = kelas_tujuan.nama_kelas
            siswa.tingkat = kelas_tujuan.tingkat
            siswa.save(update_fields=['kelas', 'tingkat'])

        berhasil += 1

    if berhasil:
        messages.success(request, f'{berhasil} siswa berhasil ditempatkan ke kelas {kelas_tujuan.nama_kelas}.')
    if sudah_di_kelas:
        messages.info(request, f'{sudah_di_kelas} siswa dilewati karena sudah berada di kelas {kelas_tujuan.nama_kelas}.')
    if ditolak:
        messages.warning(
            request,
            'Sebagian siswa TIDAK ditempatkan karena jurusannya tidak sesuai kelas tujuan: ' + ', '.join(ditolak)
        )

    return _redirect_pengelolaan_kelas(tahun_ajaran, **filter_balik)


@role_required('admin', 'super_admin')
@require_POST
def cek_nis_massal(request):
    """
    Cocokkan banyak NIS sekaligus (ditempel dari Excel / diketik, dipisah baris,
    spasi, koma, atau titik koma) untuk widget "Input NIS Massal". Hanya membaca
    data -- pemindahan sebenarnya tetap lewat tempatkan_siswa setelah konfirmasi.
    Return JSON: cocok (siswa aktif), bukan_aktif, tidak_ditemukan.
    """
    form = CekNisMassalForm(request.POST)
    if not form.is_valid():
        return JsonResponse({'error': ' '.join(kumpulkan_pesan_error(form))}, status=400)
    tahun = form.cleaned_data['tahun_ajaran']

    daftar_nis, dilihat = [], set()
    for token in re.split(r'[\s,;]+', form.cleaned_data['nis_list']):
        token = token.strip()
        if token.endswith('.0') and re.fullmatch(r'[0-9]+', token[:-2]):   # NIS dari Excel bisa berakhiran .0
            token = token[:-2]
        if token and token not in dilihat:
            dilihat.add(token)
            daftar_nis.append(token)

    if not daftar_nis:
        return JsonResponse({'error': 'Masukkan minimal satu NIS.'}, status=400)
    if len(daftar_nis) > 500:
        return JsonResponse({'error': 'Maksimal 500 NIS sekali cocokkan.'}, status=400)

    siswa_map = {s.nis: s for s in Siswa.objects.filter(nis__in=daftar_nis)}
    kelas_map = {
        r.siswa_id: r.kelas
        for r in RiwayatKelas.objects.filter(tahun_ajaran=tahun, siswa__in=list(siswa_map.values())).select_related('kelas')
    }

    cocok, bukan_aktif, tidak_ditemukan = [], [], []
    for nis in daftar_nis:
        siswa = siswa_map.get(nis)
        if siswa is None:
            tidak_ditemukan.append(nis)
        elif siswa.status != 'aktif':
            bukan_aktif.append({'nis': nis, 'status': siswa.status})
        else:
            kelas = kelas_map.get(siswa.id)
            cocok.append({
                'id': siswa.id,
                'nis': siswa.nis,
                'nama': siswa.nama or '-',
                'jurusan': siswa.jurusan or '',
                'tingkat': TINGKAT_KE_ROMAWI.get(siswa.tingkat, siswa.tingkat),
                'kelas_id': kelas.id if kelas else None,
                'kelas': kelas.nama_kelas if kelas else '',
            })

    return JsonResponse({
        'total_input': len(daftar_nis),
        'cocok': cocok,
        'bukan_aktif': bukan_aktif,
        'tidak_ditemukan': tidak_ditemukan,
    })


@role_required('admin', 'super_admin')
def naikkan_otomatis(request):
    """
    Kenaikan kelas XI ke XII secara BAWAAN (bagian 7 spesifikasi): tidak ada
    pembagian ulang, siswa dipertahankan pada kelas dengan nama yang sama
    (cuma tingkatnya berubah dari XI ke XII) di tahun ajaran tujuan.
    """
    if request.method != 'POST':
        return redirect('pengelolaan_kelas')

    tahun_ajaran_tujuan = _tahun_ajaran_post_atau_404(request)
    form = NaikkanOtomatisForm(request.POST, tahun_tujuan=tahun_ajaran_tujuan)

    if not form.is_valid():
        pesan_error_form(request, form)
        return _redirect_pengelolaan_kelas(tahun_ajaran_tujuan)

    tahun_ajaran_asal = form.cleaned_data['tahun_ajaran_asal']
    jurusan = form.cleaned_data.get('jurusan')

    riwayat_asal_qs = RiwayatKelas.objects.filter(
        tahun_ajaran=tahun_ajaran_asal, tingkat=11, siswa__status='aktif'
    ).select_related('siswa', 'kelas')
    if jurusan:
        riwayat_asal_qs = riwayat_asal_qs.filter(siswa__jurusan=jurusan)

    admin_user = pengguna_saat_ini(request)
    naik = 0

    with transaction.atomic():   # semua siswa naik bersama atau batal bersama
        for riwayat in riwayat_asal_qs:
            siswa = riwayat.siswa
            nama_lama = riwayat.kelas.nama_kelas
            potongan = nama_lama.split(' ')
            if potongan and potongan[0] == 'XI':
                potongan[0] = 'XII'
            nama_baru = ' '.join(potongan)

            kelas_tujuan, _dibuat = Kelas.objects.get_or_create(
                nama_kelas=nama_baru, tahun_ajaran=tahun_ajaran_tujuan,
                defaults={'jurusan': siswa.jurusan, 'tingkat': 12}
            )

            riwayat_tujuan_lama = RiwayatKelas.objects.filter(siswa=siswa, tahun_ajaran=tahun_ajaran_tujuan).first()
            if riwayat_tujuan_lama and riwayat_tujuan_lama.kelas_id == kelas_tujuan.id:
                continue  # sudah pernah dinaikkan ke kelas yang sama, tidak perlu diulang

            kelas_sebelumnya = riwayat_tujuan_lama.kelas if riwayat_tujuan_lama else riwayat.kelas

            RiwayatKelas.objects.update_or_create(
                siswa=siswa, tahun_ajaran=tahun_ajaran_tujuan,
                defaults={
                    'kelas': kelas_tujuan,
                    'tingkat': 12,
                    'tanggal_penempatan': timezone.now(),
                    'diubah_oleh': admin_user,
                }
            )
            LogPerubahanKelas.objects.create(
                siswa=siswa,
                kelas_sebelumnya=kelas_sebelumnya,
                kelas_baru=kelas_tujuan,
                tahun_ajaran=tahun_ajaran_tujuan,
                jenis_perubahan='kenaikan_otomatis_xi_ke_xii',
                diubah_oleh=admin_user,
            )

            if tahun_ajaran_tujuan.status == 'aktif':
                siswa.kelas = kelas_tujuan.nama_kelas
                siswa.tingkat = 12
                siswa.save(update_fields=['kelas', 'tingkat'])

            naik += 1

    if naik:
        messages.success(
            request,
            f'{naik} siswa berhasil dinaikkan otomatis dari kelas XI ke XII '
            f'(kelas dipertahankan sama) untuk tahun ajaran {tahun_ajaran_tujuan.tahun_ajaran}.'
        )
    else:
        messages.info(request, 'Tidak ada siswa tingkat XI yang perlu dinaikkan (mungkin sudah pernah diproses).')

    return _redirect_pengelolaan_kelas(tahun_ajaran_tujuan, tingkat='12')


@role_required('admin', 'super_admin')
def kelola_kelas(request):
    tahun_ajaran_terpilih = _tahun_ajaran_terpilih(request)
    daftar_tahun_ajaran = Tahun_ajaran.objects.all().order_by('-id')

    daftar_kelas = []
    if tahun_ajaran_terpilih:
        daftar_kelas = (
            Kelas.objects.filter(tahun_ajaran=tahun_ajaran_terpilih)
            .annotate(jumlah_siswa_hitung=Count('riwayat_kelas'))   # 1 query, bukan 2 per kelas
            .order_by('jurusan', 'tingkat', 'nama_kelas')
        )

    context = {
        'active_menu': 'pengelolaan_kelas',
        'daftar_tahun_ajaran': daftar_tahun_ajaran,
        'tahun_ajaran_terpilih': tahun_ajaran_terpilih,
        'daftar_kelas': daftar_kelas,
        'form_kelas': KelasForm(tahun_ajaran=tahun_ajaran_terpilih),
        'form_massal': BuatKelasMassalForm(tahun_ajaran=tahun_ajaran_terpilih),
        'form_salin': SalinKelasForm(),
        'daftar_jurusan': pilihan_jurusan(),
    }
    return render(request, 'eprestasi/pengelolaan_kelas/kelola_kelas.html', context)


@role_required('admin', 'super_admin')
def tambah_kelas(request):
    """Tambah SATU kelas ke sebuah tahun ajaran (nama kelas tidak boleh kembar di tahun yang sama)."""
    if request.method != 'POST':
        return redirect('kelola_kelas')

    tahun_ajaran = _tahun_ajaran_post_atau_404(request)
    form = KelasForm(request.POST, tahun_ajaran=tahun_ajaran)
    if form.is_valid():
        data = form.cleaned_data
        Kelas.objects.create(
            nama_kelas=data['nama_kelas'], jurusan=data['jurusan'],
            tingkat=int(data['tingkat']), tahun_ajaran=tahun_ajaran,
        )
        messages.success(request, f'Kelas "{data["nama_kelas"]}" berhasil ditambahkan.')
    else:
        pesan_error_form(request, form)
    return _redirect_kelola_kelas(tahun_ajaran.id)


def _tambah_jurusan(request, tahun_ajaran):
    """
    Tambah jurusan baru. Form-nya ada di kartu "Buat Kelas Massal" dan memakai URL
    yang sama (field tersembunyi aksi=tambah_jurusan), jadi tidak butuh route baru.
    """
    form = JurusanBaruForm(request.POST)
    if form.is_valid():
        kode = form.cleaned_data['kode_jurusan']
        with transaction.atomic():
            # Pertama kali tabel dipakai: isi dulu jurusan bawaan supaya tidak hilang dari daftar.
            if not Jurusan.objects.exists():
                for k, _label in DAFTAR_JURUSAN:
                    Jurusan.objects.get_or_create(kode=k)
            Jurusan.objects.create(kode=kode)
        messages.success(request, f'Jurusan {kode} berhasil ditambahkan.')
    else:
        pesan_error_form(request, form)
    return _redirect_kelola_kelas(tahun_ajaran.id)


@role_required('admin', 'super_admin')
def buat_kelas_massal(request):
    if request.method != 'POST':
        return redirect('kelola_kelas')

    tahun_ajaran = _tahun_ajaran_post_atau_404(request)

    if request.POST.get('aksi') == 'tambah_jurusan':
        return _tambah_jurusan(request, tahun_ajaran)

    form = BuatKelasMassalForm(request.POST, tahun_ajaran=tahun_ajaran)

    if form.is_valid():
        data = form.cleaned_data
        jurusan = data['jurusan']
        tingkat = int(data['tingkat'])
        romawi = TINGKAT_KE_ROMAWI.get(tingkat, '')

        # Pola nama: <tingkat> <nama kustom ATAU kode jurusan> <nomor>, contoh "X PPLG 1".
        # Kelas tetap tersimpan dengan jurusan yang dipilih (misal RPL), jadi
        # penempatan siswa tetap divalidasi terhadap jurusan itu.
        penanda = data.get('nama_kustom') or jurusan
        daftar_nama = [f'{romawi} {penanda} {nomor}' for nomor in range(1, data['jumlah_kelas'] + 1)]

        sudah_ada = {
            n.lower() for n in Kelas.objects.filter(tahun_ajaran=tahun_ajaran).values_list('nama_kelas', flat=True)
        }
        dibuat = 0
        dilewati = []
        for nama in daftar_nama:
            if nama.lower() in sudah_ada:
                dilewati.append(nama)
                continue
            _kelas, is_baru = Kelas.objects.get_or_create(
                nama_kelas=nama, tahun_ajaran=tahun_ajaran,
                defaults={'jurusan': jurusan, 'tingkat': tingkat}
            )
            if is_baru:
                dibuat += 1
        if dibuat:
            messages.success(request, f'{dibuat} kelas baru berhasil dibuat untuk jurusan {jurusan}.')
        if dilewati:
            messages.info(request, 'Dilewati karena sudah ada: ' + ', '.join(dilewati))
    else:
        pesan_error_form(request, form)

    return _redirect_kelola_kelas(tahun_ajaran.id)


@role_required('admin', 'super_admin')
def salin_kelas(request):
    if request.method != 'POST':
        return redirect('kelola_kelas')

    tahun_ajaran_tujuan = _tahun_ajaran_post_atau_404(request)
    form = SalinKelasForm(request.POST, tahun_tujuan=tahun_ajaran_tujuan)

    if form.is_valid():
        sumber = form.cleaned_data['tahun_ajaran_sumber']
        kelas_sumber = list(Kelas.objects.filter(tahun_ajaran=sumber))
        if not kelas_sumber:
            messages.warning(request, f'Tahun ajaran {sumber.tahun_ajaran} belum memiliki kelas untuk disalin.')
            return _redirect_kelola_kelas(tahun_ajaran_tujuan.id)

        # Satu query cek + satu bulk insert (bukan get_or_create per kelas).
        sudah_ada = {
            n.lower() for n in Kelas.objects.filter(tahun_ajaran=tahun_ajaran_tujuan).values_list('nama_kelas', flat=True)
        }
        baru = [
            Kelas(nama_kelas=k.nama_kelas, tahun_ajaran=tahun_ajaran_tujuan, jurusan=k.jurusan, tingkat=k.tingkat)
            for k in kelas_sumber if k.nama_kelas.lower() not in sudah_ada
        ]
        Kelas.objects.bulk_create(baru)
        messages.success(
            request,
            f'{len(baru)} kelas berhasil disalin dari tahun ajaran {sumber.tahun_ajaran}.'
        )
    else:
        pesan_error_form(request, form)

    return _redirect_kelola_kelas(tahun_ajaran_tujuan.id)


@role_required('admin', 'super_admin')
def hapus_kelas(request, kelas_id):
    kelas = get_object_or_404(Kelas, id=kelas_id)
    if request.method == 'POST':
        if kelas.jumlah_siswa > 0:
            messages.error(
                request,
                f'Kelas "{kelas.nama_kelas}" tidak bisa dihapus karena masih memiliki {kelas.jumlah_siswa} siswa.'
            )
        else:
            nama = kelas.nama_kelas
            tahun_ajaran_id = kelas.tahun_ajaran_id
            kelas.delete()
            messages.success(request, f'Kelas "{nama}" berhasil dihapus.')
            return _redirect_kelola_kelas(tahun_ajaran_id)
    return _redirect_kelola_kelas(kelas.tahun_ajaran_id)


@role_required('admin', 'super_admin')
def riwayat_kelas_siswa(request, siswa_id):
    siswa = get_object_or_404(Siswa, id=siswa_id)
    riwayat = (
        RiwayatKelas.objects.filter(siswa=siswa)
        .select_related('kelas', 'tahun_ajaran', 'diubah_oleh')
        .order_by('tahun_ajaran_id')  # paling lama -> paling baru
    )
    log_perubahan = (
        LogPerubahanKelas.objects.filter(siswa=siswa)
        .select_related('kelas_sebelumnya', 'kelas_baru', 'tahun_ajaran', 'diubah_oleh')
        .order_by('-waktu_perubahan')
    )
    context = {
        'active_menu': 'siswa',
        'siswa': siswa,
        'riwayat_kelas': riwayat,
        'log_perubahan': log_perubahan,
        'perjalanan_kelas': [r.kelas.nama_kelas for r in riwayat],
    }
    return render(request, 'eprestasi/pengelolaan_kelas/riwayat_siswa.html', context)


@role_required('admin', 'super_admin')
def riwayat_berdasarkan_kelas(request):
    tahun_ajaran_terpilih = _tahun_ajaran_terpilih(request)
    daftar_tahun_ajaran = Tahun_ajaran.objects.all().order_by('-id')

    jurusan_filter = request.GET.get('jurusan', '').strip()
    if jurusan_filter not in {k for k, _ in pilihan_jurusan()}:
        jurusan_filter = ''
    kelas_id = v.ke_int_aman(request.GET.get('kelas')) or ''

    daftar_kelas = []
    if tahun_ajaran_terpilih:
        kelas_qs = Kelas.objects.filter(tahun_ajaran=tahun_ajaran_terpilih)
        if jurusan_filter:
            kelas_qs = kelas_qs.filter(jurusan=jurusan_filter)
        daftar_kelas = kelas_qs.order_by('jurusan', 'tingkat', 'nama_kelas')

    kelas_terpilih = None
    daftar_riwayat = []
    if kelas_id:
        kelas_terpilih = Kelas.objects.filter(id=kelas_id).first()
        if kelas_terpilih:
            daftar_riwayat = list(
                RiwayatKelas.objects.filter(kelas=kelas_terpilih)
                .select_related('siswa')
                .order_by('siswa__nama')
            )
            # Lengkapi "perjalanan siswa" (seluruh riwayat kelasnya, urut lama -> baru).
            # Satu query untuk semua siswa (sebelumnya 1 query per siswa).
            perjalanan = {}
            for rk in (RiwayatKelas.objects.filter(siswa_id__in=[r.siswa_id for r in daftar_riwayat])
                       .select_related('kelas', 'tahun_ajaran').order_by('tahun_ajaran_id')):
                perjalanan.setdefault(rk.siswa_id, []).append(rk)
            for r in daftar_riwayat:
                r.perjalanan = perjalanan.get(r.siswa_id, [])

    context = {
        'active_menu': 'pengelolaan_kelas',
        'daftar_tahun_ajaran': daftar_tahun_ajaran,
        'tahun_ajaran_terpilih': tahun_ajaran_terpilih,
        'daftar_jurusan': pilihan_jurusan(),
        'jurusan_filter': jurusan_filter,
        'daftar_kelas': daftar_kelas,
        'kelas_id': kelas_id,
        'kelas_terpilih': kelas_terpilih,
        'daftar_riwayat': daftar_riwayat,
    }
    return render(request, 'eprestasi/pengelolaan_kelas/riwayat_kelas.html', context)


@role_required('admin', 'super_admin')
def log_perubahan_kelas(request):
    q = v.rapikan_spasi(request.GET.get('q', ''))[:100]
    tahun_ajaran_id = v.ke_int_aman(request.GET.get('tahun_ajaran')) or ''

    log_qs = LogPerubahanKelas.objects.select_related(
        'siswa', 'kelas_sebelumnya', 'kelas_baru', 'tahun_ajaran', 'diubah_oleh'
    )
    if q:
        log_qs = log_qs.filter(Q(siswa__nama__icontains=q) | Q(siswa__nis__icontains=q))
    if tahun_ajaran_id:
        log_qs = log_qs.filter(tahun_ajaran_id=tahun_ajaran_id)

    context = {
        'active_menu': 'pengelolaan_kelas',
        'daftar_tahun_ajaran': Tahun_ajaran.objects.all().order_by('-id'),
        'tahun_ajaran_id': tahun_ajaran_id,
        'q': q,
        'daftar_log': log_qs[:300],
    }
    return render(request, 'eprestasi/pengelolaan_kelas/log_perubahan.html', context)


# ======================================================================
# 8. KELULUSAN & ALUMNI
# ======================================================================


SORT_KELULUSAN = {
    'nama_asc': ('nama',), 'nama_desc': ('-nama',),
    'nis_asc': ('nis',), 'nis_desc': ('-nis',),
    'kelas_asc': ('kelas', 'nama'), 'kelas_desc': ('-kelas', 'nama'),
    'jurusan_asc': ('jurusan', 'nama'), 'jurusan_desc': ('-jurusan', 'nama'),
    'tahun_ajaran_asc': ('tahun_ajaran_label', 'nama'), 'tahun_ajaran_desc': ('-tahun_ajaran_label', 'nama'),
    'status_kelulusan_asc': ('status_kelulusan', 'nama'), 'status_kelulusan_desc': ('-status_kelulusan', 'nama'),
    'status_asc': ('status', 'nama'), 'status_desc': ('-status', 'nama'),
    'tanggal_asc': ('tanggal_kelulusan', 'nama'), 'tanggal_desc': ('-tanggal_kelulusan', 'nama'),
}


DEFAULT_SORT_KELULUSAN = 'nama_asc'


SORT_ALUMNI = {
    'nama_asc': ('nama',), 'nama_desc': ('-nama',),
    'nis_asc': ('nis',), 'nis_desc': ('-nis',),
    'jurusan_asc': ('jurusan', 'nama'), 'jurusan_desc': ('-jurusan', 'nama'),
    'kelas_asc': ('kelas', 'nama'), 'kelas_desc': ('-kelas', 'nama'),
    'tahun_lulus_asc': ('tanggal_kelulusan', 'nama'), 'tahun_lulus_desc': ('-tanggal_kelulusan', 'nama'),
}


DEFAULT_SORT_ALUMNI = 'tahun_lulus_desc'


STATUS_KELULUSAN_LABEL = dict(Siswa.STATUS_KELULUSAN_CHOICES)


STATUS_SISWA_LABEL = {'aktif': 'Aktif', 'nonaktif': 'Nonaktif', 'alumni': 'Alumni'}


def _annotate_tahun_ajaran(qs):
    """
    Lampirkan label tahun ajaran terakhir siswa berada di tingkat XII,
    diambil dari RiwayatKelas (kelas siswa bisa berubah tiap tahun ajaran,
    lihat models.py). Kalau siswa belum pernah tercatat di RiwayatKelas
    (misal input manual lama), label ini kosong.
    """
    latest = (
        RiwayatKelas.objects.filter(siswa=OuterRef('pk'), tingkat=12)
        .order_by('-tahun_ajaran_id')
        .values('tahun_ajaran__tahun_ajaran')[:1]
    )
    return qs.annotate(tahun_ajaran_label=Subquery(latest))


@role_required('admin', 'super_admin')
def kelulusan_alumni(request):
    tab = request.GET.get('tab', 'kelulusan')
    if tab not in ('kelulusan', 'alumni'):
        tab = 'kelulusan'

    kelas_xii_qs = Siswa.objects.filter(tingkat=12).exclude(status='keluar')
    statistik = {
        'total_xii': kelas_xii_qs.count(),
        'siap_diproses': kelas_xii_qs.filter(status='aktif', status_kelulusan='belum_diproses').count(),
        'lulus': Siswa.objects.filter(status_kelulusan='lulus').count(),
        'belum_lulus': Siswa.objects.filter(status_kelulusan='tidak_lulus').count(),
        'alumni': Siswa.objects.filter(status='alumni').count(),
    }

    context = {
        'active_menu': 'kelulusan_alumni',
        'active_tab': tab,
        'statistik': statistik,
        'daftar_jurusan': pilihan_jurusan(),
    }

    if tab == 'alumni':
        context.update(_build_alumni_context(request))
    else:
        context.update(_build_kelulusan_context(request))

    return render(request, 'eprestasi/kelulusan/list.html', context)


def _build_kelulusan_context(request):
    # Parameter URL divalidasi (angka / pilihan yang dikenal); nilai aneh diabaikan, bukan error 500.
    q = v.rapikan_spasi(request.GET.get('q', ''))[:100]
    f_tahun_ajaran = v.ke_int_aman(request.GET.get('tahun_ajaran')) or ''
    f_kelas = v.rapikan_spasi(request.GET.get('kelas', ''))[:100]
    f_jurusan = request.GET.get('jurusan', '').strip()
    if f_jurusan not in {k for k, _ in pilihan_jurusan()}:
        f_jurusan = ''
    f_status_kelulusan = request.GET.get('status_kelulusan', '').strip()
    if f_status_kelulusan not in STATUS_KELULUSAN_LABEL:
        f_status_kelulusan = ''
    f_status_siswa = request.GET.get('status_siswa', '').strip()
    if f_status_siswa not in STATUS_SISWA_LABEL:
        f_status_siswa = ''
    sort = request.GET.get('sort', DEFAULT_SORT_KELULUSAN)
    if sort not in SORT_KELULUSAN:
        sort = DEFAULT_SORT_KELULUSAN

    siswa_qs = Siswa.objects.filter(tingkat=12).exclude(status='keluar').select_related('users')
    siswa_qs = _annotate_tahun_ajaran(siswa_qs)

    if q:
        siswa_qs = siswa_qs.filter(Q(nama__icontains=q) | Q(nis__icontains=q))
    if f_tahun_ajaran:
        siswa_qs = siswa_qs.filter(riwayat_kelas__tahun_ajaran_id=f_tahun_ajaran, riwayat_kelas__tingkat=12)
    if f_kelas:
        siswa_qs = siswa_qs.filter(kelas=f_kelas)
    if f_jurusan:
        siswa_qs = siswa_qs.filter(jurusan=f_jurusan)
    if f_status_kelulusan:
        siswa_qs = siswa_qs.filter(status_kelulusan=f_status_kelulusan)
    if f_status_siswa:
        siswa_qs = siswa_qs.filter(status=f_status_siswa)

    siswa_qs = siswa_qs.distinct().order_by(*SORT_KELULUSAN[sort])

    sort_toggle = _build_sort_toggle(sort, [
        'nis', 'nama', 'kelas', 'jurusan', 'tahun_ajaran', 'status_kelulusan', 'status', 'tanggal',
    ])

    daftar_kelas_xii = (
        Siswa.objects.filter(tingkat=12).exclude(kelas='').exclude(kelas__isnull=True)
        .values_list('kelas', flat=True).distinct().order_by('kelas')
    )
    daftar_tahun_ajaran = (
        RiwayatKelas.objects.filter(tingkat=12).select_related('tahun_ajaran')
        .values_list('tahun_ajaran_id', 'tahun_ajaran__tahun_ajaran').distinct().order_by('-tahun_ajaran_id')
    )

    paginator = Paginator(siswa_qs, PAGE_SIZE)
    page_obj = paginator.get_page(request.GET.get('page'))

    filter_aktif = sum(bool(x) for x in [f_tahun_ajaran, f_kelas, f_jurusan, f_status_kelulusan, f_status_siswa])

    return {
        'page_obj': page_obj,
        'q': q,
        'sort': sort,
        'f_tahun_ajaran': f_tahun_ajaran,
        'f_kelas': f_kelas,
        'f_jurusan': f_jurusan,
        'f_status_kelulusan': f_status_kelulusan,
        'f_status_siswa': f_status_siswa,
        'filter_aktif_count': filter_aktif,
        'daftar_kelas_xii': daftar_kelas_xii,
        'daftar_tahun_ajaran': daftar_tahun_ajaran,
        'status_kelulusan_choices': Siswa.STATUS_KELULUSAN_CHOICES,
        'sort_toggle': sort_toggle,
        'item_label': 'siswa',
    }


def _build_alumni_context(request):
    q = v.rapikan_spasi(request.GET.get('q', ''))[:100]
    f_tahun_lulus = v.ke_int_aman(request.GET.get('tahun_lulus'), minimal=1990, maksimal=2100) or ''
    f_jurusan = request.GET.get('jurusan', '').strip()
    if f_jurusan not in {k for k, _ in pilihan_jurusan()}:
        f_jurusan = ''
    f_kelas = v.rapikan_spasi(request.GET.get('kelas', ''))[:100]
    sort = request.GET.get('sort', DEFAULT_SORT_ALUMNI)
    if sort not in SORT_ALUMNI:
        sort = DEFAULT_SORT_ALUMNI

    alumni_qs = Siswa.objects.filter(status='alumni').select_related('users')

    if q:
        alumni_qs = alumni_qs.filter(Q(nama__icontains=q) | Q(nis__icontains=q))
    if f_tahun_lulus:
        alumni_qs = alumni_qs.filter(tanggal_kelulusan__year=f_tahun_lulus)
    if f_jurusan:
        alumni_qs = alumni_qs.filter(jurusan=f_jurusan)
    if f_kelas:
        alumni_qs = alumni_qs.filter(kelas=f_kelas)

    alumni_qs = alumni_qs.order_by(*SORT_ALUMNI[sort])

    sort_toggle = _build_sort_toggle(sort, ['nis', 'nama', 'jurusan', 'kelas', 'tahun_lulus'])

    daftar_tahun_lulus = (
        Siswa.objects.filter(status='alumni').exclude(tanggal_kelulusan__isnull=True)
        .dates('tanggal_kelulusan', 'year', order='DESC')
    )
    daftar_kelas_alumni = (
        Siswa.objects.filter(status='alumni').exclude(kelas='').exclude(kelas__isnull=True)
        .values_list('kelas', flat=True).distinct().order_by('kelas')
    )

    paginator = Paginator(alumni_qs, PAGE_SIZE)
    page_obj = paginator.get_page(request.GET.get('page'))

    filter_aktif = sum(bool(x) for x in [f_tahun_lulus, f_jurusan, f_kelas])

    return {
        'page_obj': page_obj,
        'q': q,
        'sort': sort,
        'f_tahun_lulus': f_tahun_lulus,
        'f_jurusan': f_jurusan,
        'f_kelas': f_kelas,
        'filter_aktif_count': filter_aktif,
        'daftar_tahun_lulus': [d.year for d in daftar_tahun_lulus],
        'daftar_kelas_alumni': daftar_kelas_alumni,
        'sort_toggle': sort_toggle,
        'item_label': 'alumni',
    }


def _kembali_ke_kelulusan(request, tab='kelulusan'):
    qd = request.POST.copy()
    qd.pop('siswa_ids', None)
    qd['tab'] = tab
    query = qd.urlencode()
    url = reverse('kelulusan_alumni')
    return redirect(f'{url}?{query}' if query else f'{url}?tab={tab}')


@role_required('admin', 'super_admin')
def proses_kelulusan(request):
    """
    Aksi massal "Proses Kelulusan": siswa terpilih (tingkat XII) ditetapkan
    Lulus -> status siswa otomatis berubah jadi Alumni. Data siswa TIDAK
    dihapus, riwayat & relasi prestasi tetap tersambung.
    """
    if request.method != 'POST':
        return redirect('kelulusan_alumni')

    siswa_ids = _ids_terpilih(request, 'Pilih minimal satu siswa yang akan diproses kelulusannya.', nama='siswa_ids')
    if siswa_ids is None:
        return _kembali_ke_kelulusan(request)

    siswa_terpilih = Siswa.objects.filter(id__in=siswa_ids, tingkat=12).exclude(status='keluar')
    hari_ini = timezone.localdate()
    nama_terproses = list(siswa_terpilih.values_list('nama', flat=True))
    jumlah = siswa_terpilih.update(status_kelulusan='lulus', status='alumni', tanggal_kelulusan=hari_ini)

    if jumlah:
        catat_aktivitas(
            request, 'kelulusan_diproses',
            'Admin memproses kelulusan siswa',
            f'{jumlah} siswa kelas XII ditetapkan Lulus dan berpindah status menjadi Alumni: '
            f'{", ".join(nama_terproses[:10])}{" dan lainnya" if jumlah > 10 else ""}.',
            modul='kelulusan',
        )
        messages.success(request, f'{jumlah} siswa berhasil ditetapkan sebagai Lulus dan kini berstatus Alumni.')
    else:
        messages.warning(request, 'Tidak ada siswa yang berhasil diproses (pastikan siswa berada di tingkat XII).')

    return _kembali_ke_kelulusan(request)


@role_required('admin', 'super_admin')
def tandai_tidak_lulus(request):
    """
    Aksi sekunder: menandai siswa tingkat XII sebagai Tidak Lulus. Berbeda
    dari "Proses Kelulusan", status siswa TIDAK berubah menjadi alumni
    (siswa tetap aktif, hanya status_kelulusan yang berubah), karena siswa
    masih berpotensi mengulang/diproses ulang di kemudian hari.
    """
    if request.method != 'POST':
        return redirect('kelulusan_alumni')

    siswa_ids = _ids_terpilih(request, 'Pilih minimal satu siswa terlebih dahulu.', nama='siswa_ids')
    if siswa_ids is None:
        return _kembali_ke_kelulusan(request)

    siswa_terpilih = Siswa.objects.filter(id__in=siswa_ids, tingkat=12).exclude(status='keluar')
    nama_terproses = list(siswa_terpilih.values_list('nama', flat=True))
    jumlah = siswa_terpilih.update(status_kelulusan='tidak_lulus')

    if jumlah:
        catat_aktivitas(
            request, 'kelulusan_diproses',
            'Admin menandai siswa tidak lulus',
            f'{jumlah} siswa kelas XII ditandai Tidak Lulus: '
            f'{", ".join(nama_terproses[:10])}{" dan lainnya" if jumlah > 10 else ""}.',
            modul='kelulusan',
        )
        messages.success(request, f'{jumlah} siswa berhasil ditandai sebagai Tidak Lulus.')

    return _kembali_ke_kelulusan(request)


# ======================================================================
# 9. IMPORT SISWA (EXCEL)
# ======================================================================


# Dipakai buat mencocokkan isi kolom Kelas/Jurusan di Excel (bebas huruf besar/kecil,
# spasi nyasar di ujung). Kelas dicocokkan dengan Kelas tahun ajaran AKTIF, jurusan dengan pilihan di model Siswa.
logger = logging.getLogger(__name__)


_JURUSAN_VALID = {label.strip().lower(): value for value, label in Siswa.JURUSAN_CHOICES}


# Karakter yang gampang ketuker (0/O, 1/l/I) sengaja dibuang dari kandidat
# password acak, supaya siswa tidak salah ketik pas ngetik ulang dari kertas.
_ALFABET_PASSWORD = ''.join(c for c in string.ascii_letters + string.digits if c not in '0O1lI')


def _buat_password_acak(panjang=8):
    return ''.join(secrets.choice(_ALFABET_PASSWORD) for _ in range(panjang))


@role_required('admin', 'super_admin')
def download_template_siswa(request):
    """Kasih file Excel kosong dengan header yang benar, supaya admin tidak
    perlu nebak-nebak nama kolom yang diharapkan sistem."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'Import Siswa'
    ws.append(['NIS', 'Password (opsional)', 'Nama (opsional)', 'Kelas (opsional)', 'Jurusan (opsional)'])
    ws.append(['10001', 'passwordsiswa1', 'Muhammad Rizky', 'X RPL 1', 'RPL'])
    ws.append(['10002', '', '', '', ''])  # contoh: semua kolom opsional boleh dikosongkan

    ws.column_dimensions['A'].width = 15
    ws.column_dimensions['B'].width = 20
    ws.column_dimensions['C'].width = 25
    ws.column_dimensions['D'].width = 15
    ws.column_dimensions['E'].width = 15

    # Sheet kedua -- daftar nilai Kelas & Jurusan yang valid, supaya admin
    # tinggal copy-paste persis (kalau salah ketik, kolom itu dikosongkan
    # otomatis saat import, bukan bikin baris gagal).
    ws_ref = wb.create_sheet('Pilihan Kelas & Jurusan')
    ws_ref.append(['Kelas', 'Jurusan'])
    tahun = tahun_ajaran_aktif()
    kelas_list = list(Kelas.objects.filter(tahun_ajaran=tahun).order_by('jurusan', 'tingkat', 'nama_kelas').values_list('nama_kelas', flat=True)) if tahun else []
    jurusan_list = [label for _, label in Siswa.JURUSAN_CHOICES]
    for i in range(max(len(kelas_list), len(jurusan_list))):
        ws_ref.append([
            kelas_list[i] if i < len(kelas_list) else '',
            jurusan_list[i] if i < len(jurusan_list) else '',
        ])
    ws_ref.column_dimensions['A'].width = 15
    ws_ref.column_dimensions['B'].width = 15

    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)

    response = HttpResponse(
        buffer.read(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = 'attachment; filename="template_import_siswa.xlsx"'
    return response


def _cocokkan_pilihan(nilai_mentah, kamus_valid):
    """
    Cocokkan 1 nilai dari Excel (misal 'x rpl 1' atau ' RPL ') terhadap
    pilihan resmi di model (misal 'X RPL 1' / 'RPL'), tanpa peduli huruf
    besar/kecil atau spasi nyasar. Return (value_tersimpan, cocok:boolean).
    Kalau tidak ketemu, value_tersimpan=None dan cocok=False -- kolom itu
    dikosongkan saja, TIDAK menggagalkan seluruh baris.
    """
    if not nilai_mentah:
        return None, True  # memang sengaja dikosongkan, bukan salah ketik
    kunci = str(nilai_mentah).strip().lower()
    if kunci in kamus_valid:
        return kamus_valid[kunci], True
    return None, False


def _buat_konteks_import():
    """Data pendukung yang sama untuk semua baris dalam satu proses import."""
    tahun_aktif = tahun_ajaran_aktif()
    kelas_aktif = (
        {k.nama_kelas.strip().lower(): k for k in Kelas.objects.filter(tahun_ajaran=tahun_aktif)}
        if tahun_aktif else {}
    )
    return {'kelas_aktif': kelas_aktif}


def _proses_satu_baris(baris_ke, row, konteks, nis_dipakai_di_file, berhasil, gagal):
    """
    Proses SATU baris Excel: validasi lalu bikin akun siswa. Hasilnya ditambahkan
    ke list `berhasil` atau `gagal`. Dipakai bersama oleh import biasa (sekali jalan)
    dan import dengan progres (per batch), supaya aturannya tidak bisa berbeda.
    """
    row = list(row)
    if not row or row[0] is None or str(row[0]).strip() == '':
        return  # baris kosong, lewati saja (jangan dianggap error)

    nis = v.rapikan_spasi(row[0])
    # openpyxl bisa balikin angka NIS sebagai float (misal 10001.0) kalau
    # kolomnya keformat "Number" di Excel -- rapikan biar jadi "10001" bukan "10001.0"
    if nis.endswith('.0'):
        nis = nis[:-2]

    # ── Validasi isi baris (aturan sama persis dengan form tambah siswa) ──
    try:
        v.validasi_nis(nis)
    except ValidationError as e:
        gagal.append({'baris': baris_ke, 'nis': nis, 'alasan': e.messages[0]})
        return

    password_dari_file = None
    if len(row) > 1 and row[1] is not None and str(row[1]).strip() != '':
        password_dari_file = str(row[1]).strip()
        try:
            v.validasi_password(password_dari_file)
        except ValidationError as e:
            gagal.append({'baris': baris_ke, 'nis': nis, 'alasan': e.messages[0]})
            return

    nama_dari_file = ''
    if len(row) > 2 and row[2] is not None and str(row[2]).strip() != '':
        nama_dari_file = v.rapikan_spasi(v.hapus_tag_html(str(row[2])))
        try:
            v.validasi_nama_orang(nama_dari_file)
            if len(nama_dari_file) > v.NAMA_MAX:
                raise ValidationError(f'Nama maksimal {v.NAMA_MAX} karakter.')
        except ValidationError as e:
            gagal.append({'baris': baris_ke, 'nis': nis, 'alasan': e.messages[0]})
            return

    kelas_mentah = row[3] if len(row) > 3 else None
    jurusan_mentah = row[4] if len(row) > 4 else None

    kelas_obj, kelas_cocok = _cocokkan_pilihan(kelas_mentah, konteks['kelas_aktif'])
    jurusan_value, jurusan_cocok = _cocokkan_pilihan(jurusan_mentah, _JURUSAN_VALID)

    if nis in nis_dipakai_di_file:
        gagal.append({'baris': baris_ke, 'nis': nis, 'alasan': 'NIS dobel di dalam file ini'})
        return

    if Siswa.objects.filter(nis=nis).exists():
        gagal.append({'baris': baris_ke, 'nis': nis, 'alasan': 'NIS sudah terdaftar di sistem'})
        return

    if Kesiswaan.objects.filter(nip=nis).exists():
        gagal.append({'baris': baris_ke, 'nis': nis, 'alasan': 'NIS sama dengan NIP kesiswaan yang sudah ada'})
        return

    # Jurusan kelas harus sama dengan jurusan siswa. Kalau jurusan di file kosong,
    # ikut jurusan kelas; kalau bentrok, kelas dikosongkan (akun tetap dibuat).
    kelas_bentrok = False
    if kelas_obj:
        if not jurusan_value:
            jurusan_value = kelas_obj.jurusan
        elif jurusan_value != kelas_obj.jurusan:
            kelas_bentrok = True
            kelas_obj = None

    nis_dipakai_di_file.add(nis)
    password_otomatis = not password_dari_file
    password = password_dari_file or _buat_password_acak()
    username = _generate_username(nis, bersihkan_akun_sisa=True)

    # Atomic per baris: kalau pembuatan Siswa gagal, akun Users-nya ikut dibatalkan
    # (tidak ada akun sisa tanpa data siswa).
    with transaction.atomic():
        user_account = Users.objects.create(
            username=username,
            password=make_password(password),
            role='siswa',
        )
        siswa_baru = Siswa.objects.create(
            users=user_account,
            nis=nis,
            status='aktif',
            nama=nama_dari_file,
            jurusan=jurusan_value,
        )
        if kelas_obj:
            tempatkan_ke_kelas(siswa_baru, kelas_obj, None, alasan='Import Excel')

    # Catatan kalau Kelas/Jurusan di file tidak cocok pilihan resmi --
    # akun TETAP dibuat, kolom itu cuma dikosongkan (siswa isi manual nanti).
    catatan = []
    if kelas_mentah and not kelas_cocok:
        catatan.append(f"Kelas '{kelas_mentah}' tidak ada di tahun ajaran aktif, dikosongkan")
    if kelas_bentrok:
        catatan.append(f"Kelas '{kelas_mentah}' tidak sesuai jurusan '{jurusan_mentah}', dikosongkan")
    if jurusan_mentah and not jurusan_cocok:
        catatan.append(f"Jurusan '{jurusan_mentah}' tidak dikenali, dikosongkan")

    berhasil.append({
        'baris': baris_ke,
        'nis': nis,
        'username': username,
        'password': password,
        'password_otomatis': password_otomatis,   # True = kolom password di Excel kosong
        'nama': nama_dari_file,
        'kelas': kelas_obj.nama_kelas if kelas_obj else None,
        'jurusan': jurusan_value,
        'catatan': '; '.join(catatan),
    })


def _proses_satu_baris_aman(baris_ke, row, konteks, nis_dipakai_di_file, berhasil, gagal):
    """Sama seperti _proses_satu_baris, tapi error tak terduga di satu baris tidak menghentikan baris lain."""
    try:
        _proses_satu_baris(baris_ke, row, konteks, nis_dipakai_di_file, berhasil, gagal)
    except Exception:
        logger.exception('Import siswa: gagal memproses baris %s', baris_ke)
        nis = str(row[0]).strip() if row and row[0] is not None else '-'
        gagal.append({'baris': baris_ke, 'nis': nis, 'alasan': 'Terjadi kesalahan saat menyimpan baris ini'})


def _baca_baris_excel(file_excel):
    """
    Baca file Excel jadi list [(nomor_baris, [5 kolom sebagai teks/None])], baris kosong dibuang.
    Return (baris, pesan_error). Nilai dijadikan teks supaya aman disimpan di session.
    """
    try:
        wb = openpyxl.load_workbook(file_excel, read_only=True, data_only=True)
        ws = wb.active
        hasil = []
        for baris_ke, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
            if not row or row[0] is None or str(row[0]).strip() == '':
                continue
            kolom = [None if sel is None else str(sel) for sel in list(row)[:5]]
            kolom += [None] * (5 - len(kolom))
            hasil.append([baris_ke, kolom])
            if len(hasil) > MAKS_BARIS_IMPORT:   # Range validation: batasi ukuran sekali import
                return [], f'Maksimal {MAKS_BARIS_IMPORT} siswa sekali import. Pecah file menjadi beberapa bagian.'
        return hasil, None
    except Exception:
        return [], 'File tidak bisa dibaca. Pastikan formatnya .xlsx yang valid (bukan .xls atau .csv).'


def _proses_import_siswa(file_excel):
    """
    Import sekali jalan (dipakai kalau JavaScript tidak aktif).
    Return dict: {'berhasil': [...], 'gagal': [...], 'error_file': str|None}

    Kolom: A=NIS (wajib), B=Password (opsional), C=Nama (opsional),
    D=Kelas (opsional), E=Jurusan (opsional). Baris 1 dianggap header, diabaikan.

    Nama/Kelas/Jurusan diisi langsung ke akun siswa kalau ada di file -- jadi
    pas siswa pertama kali buka halaman "Lengkapi Profil", field itu SUDAH
    keisi otomatis dan siswa tinggal melengkapi sisanya (email, no HP, foto).
    """
    baris, error = _baca_baris_excel(file_excel)
    if error:
        return {'berhasil': [], 'gagal': [], 'error_file': error}

    berhasil, gagal, nis_dipakai = [], [], set()
    konteks = _buat_konteks_import()
    for baris_ke, kolom in baris:
        _proses_satu_baris_aman(baris_ke, kolom, konteks, nis_dipakai, berhasil, gagal)
    return {'berhasil': berhasil, 'gagal': gagal, 'error_file': None}


@role_required('admin', 'super_admin')
def import_siswa(request):
    if request.method == 'POST':
        form = ImportSiswaForm(request.POST, request.FILES)
        if form.is_valid():
            hasil = _proses_import_siswa(form.cleaned_data['file_excel'])

            if hasil['error_file']:
                messages.error(request, hasil['error_file'])
                return render(request, 'eprestasi/siswa/import.html', {'form': form, 'active_menu': 'siswa'})

            # Disimpan sementara di session, dipakai buat nampilin ringkasan +
            # buat tombol download kredensial (halaman berikutnya, request terpisah).
            request.session['hasil_import_siswa'] = hasil

            messages.success(
                request,
                f"Import selesai: {len(hasil['berhasil'])} berhasil, {len(hasil['gagal'])} gagal."
            )
            return redirect('siswa_import_hasil')
    else:
        form = ImportSiswaForm()

    context = {'form': form, 'active_menu': 'siswa', 'ada_hasil_terakhir': bool(request.session.get('hasil_import_siswa'))}
    return render(request, 'eprestasi/siswa/import.html', context)


@role_required('admin', 'super_admin')
def hasil_import_siswa(request):
    hasil = request.session.get('hasil_import_siswa')
    if hasil is None:
        messages.error(request, 'Tidak ada hasil import untuk ditampilkan. Silakan import ulang.')
        return redirect('siswa_import')

    context = {
        'active_menu': 'siswa',
        'berhasil': hasil['berhasil'],
        'gagal': hasil['gagal'],
        'jumlah_password_otomatis': sum(1 for b in hasil['berhasil'] if b.get('password_otomatis')),
        'filter_otomatis': request.GET.get('filter') == 'otomatis',
    }
    return render(request, 'eprestasi/siswa/import_hasil.html', context)


@role_required('admin', 'super_admin')
def download_hasil_import(request):
    """
    Download daftar username+password yang BARU dibuat, dalam bentuk CSV.
    Ini SATU-SATUNYA kesempatan admin bisa lihat password aslinya -- setelah
    ini cuma tersimpan dalam bentuk hash, tidak bisa dilihat lagi selamanya.
    """
    hasil = request.session.get('hasil_import_siswa')
    if hasil is None or not hasil['berhasil']:
        messages.error(request, 'Tidak ada data untuk diunduh.')
        return redirect('siswa_import')

    lines = ['NIS,Username,Password']
    for item in hasil['berhasil']:
        lines.append(f"{item['nis']},{item['username']},{item['password']}")
    isi_csv = '\n'.join(lines)

    response = HttpResponse(isi_csv, content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="kredensial_siswa_baru.csv"'
    return response


BATCH_BARIS = 10
MAKS_BARIS_IMPORT = 2000


_KUNCI_JOB = 'import_siswa_job'


_KUNCI_INFO = 'import_siswa_info'  # status ringkas untuk widget global: {'token','state','total','diproses',...}


def _json_error(pesan, status=400):
    return JsonResponse({'ok': False, 'error': pesan}, status=status)


def _ringkasan(hasil):
    return {
        'berhasil': len(hasil['berhasil']),
        'gagal': len(hasil['gagal']),
        'password_otomatis': sum(1 for b in hasil['berhasil'] if b.get('password_otomatis')),
    }


@role_required('admin', 'super_admin')
@require_POST
def import_siswa_mulai(request):
    form = ImportSiswaForm(request.POST, request.FILES)
    if not form.is_valid():
        pesan = ' '.join(kumpulkan_pesan_error(form)) or 'File tidak valid.'
        return _json_error(pesan)

    baris, error = _baca_baris_excel(form.cleaned_data['file_excel'])
    if error:
        return _json_error(error)
    if not baris:
        return _json_error('Tidak ada data siswa di file ini. Pastikan kolom NIS terisi mulai dari baris ke-2.')

    token = secrets.token_hex(8)
    request.session[_KUNCI_JOB] = {'token': token, 'baris': baris, 'posisi': 0, 'nis_file': []}
    # Hasil kosong disiapkan dari awal supaya halaman hasil bisa dibuka walau proses terhenti di tengah jalan.
    request.session['hasil_import_siswa'] = {'berhasil': [], 'gagal': [], 'error_file': None}
    request.session[_KUNCI_INFO] = {'token': token, 'state': 'jalan', 'total': len(baris), 'diproses': 0}
    return JsonResponse({'ok': True, 'token': token, 'total': len(baris), 'batch': BATCH_BARIS})


@role_required('admin', 'super_admin')
@require_POST
def import_siswa_proses(request):
    job = request.session.get(_KUNCI_JOB)
    if not job or job.get('token') != request.POST.get('token'):
        return _json_error('Proses import tidak ditemukan atau sudah dibatalkan. Silakan mulai ulang.', status=409)

    hasil = request.session.get('hasil_import_siswa') or {'berhasil': [], 'gagal': [], 'error_file': None}

    # Pengaman: kalau klien mengirim posisi yang sudah tertinggal (permintaan ganda dari halaman
    # lama/baru), jangan proses ulang; cukup kembalikan progres terkini.
    posisi_klien = request.POST.get('posisi')
    posisi_int = v.ke_int_aman(posisi_klien)
    if posisi_int is not None and posisi_int != job['posisi']:
        total = len(job['baris'])
        data = {'ok': True, 'selesai': False, 'diproses': job['posisi'], 'total': total,
                'persen': int(job['posisi'] * 100 / total)}
        data.update(_ringkasan(hasil))
        return JsonResponse(data)

    nis_dipakai = set(job['nis_file'])
    konteks = _buat_konteks_import()

    awal = job['posisi']
    for baris_ke, kolom in job['baris'][awal:awal + BATCH_BARIS]:
        _proses_satu_baris_aman(baris_ke, kolom, konteks, nis_dipakai, hasil['berhasil'], hasil['gagal'])
        job['posisi'] += 1
    job['nis_file'] = sorted(nis_dipakai)

    total = len(job['baris'])
    selesai = job['posisi'] >= total
    request.session['hasil_import_siswa'] = hasil
    request.session[_KUNCI_INFO] = {
        'token': job['token'], 'state': 'selesai' if selesai else 'jalan',
        'total': total, 'diproses': job['posisi'],
    }
    if selesai:
        request.session.pop(_KUNCI_JOB, None)
    else:
        request.session[_KUNCI_JOB] = job

    data = {
        'ok': True, 'selesai': selesai, 'diproses': job['posisi'], 'total': total,
        'persen': 100 if selesai else int(job['posisi'] * 100 / total),
    }
    data.update(_ringkasan(hasil))
    return JsonResponse(data)


@role_required('admin', 'super_admin')
@require_POST
def import_siswa_batal(request):
    """Hentikan import. Siswa yang sudah dibuat tetap tersimpan; sisa baris tidak diproses."""
    request.session.pop(_KUNCI_JOB, None)
    info = request.session.get(_KUNCI_INFO)
    if info and info.get('state') == 'jalan':
        info['state'] = 'batal'
        request.session[_KUNCI_INFO] = info
    return JsonResponse({'ok': True})


@role_required('admin', 'super_admin')
def import_siswa_status(request):
    """Dipakai widget global di semua halaman admin untuk menampilkan/melanjutkan progres."""
    info = request.session.get(_KUNCI_INFO)
    if not info:
        return JsonResponse({'ok': True, 'aktif': False})
    hasil = request.session.get('hasil_import_siswa') or {'berhasil': [], 'gagal': []}
    data = {'ok': True, 'aktif': True, 'token': info['token'], 'state': info['state'],
            'total': info['total'], 'diproses': info['diproses'],
            'selesai': info['state'] == 'selesai'}
    data.update(_ringkasan(hasil))
    return JsonResponse(data)


@role_required('admin', 'super_admin')
@require_POST
def import_siswa_tutup(request):
    """Widget ditutup pengguna setelah import selesai/dibatalkan."""
    info = request.session.get(_KUNCI_INFO)
    if info and info.get('state') != 'jalan':
        request.session.pop(_KUNCI_INFO, None)
    return JsonResponse({'ok': True})


# ======================================================================
# 10. MASTER DATA PRESTASI
# ======================================================================


@role_required('admin', 'super_admin')
@require_http_methods(['GET', 'POST'])
def master_prestasi(request):
    if request.method == 'POST':
        aksi = request.POST.get('aksi', '')

        if aksi == 'tambah_kategori':
            form = MasterNamaForm(request.POST)
            if not form.is_valid():
                pesan_error_form(request, form)
            else:
                nama = form.cleaned_data['nama']
                kode = slugify(nama)[:50]
                if not kode or KategoriPrestasi.objects.filter(kode=kode).exists():
                    messages.error(request, 'Kategori dengan nama itu sudah ada.')
                else:
                    with transaction.atomic():
                        urutan = (KategoriPrestasi.objects.count() + 1)
                        kat = KategoriPrestasi.objects.create(kode=kode, nama=nama, urutan=urutan)
                        SubkategoriPrestasi.objects.create(kategori=kat, nama='Lainnya', adalah_lainnya=True, urutan=999)
                    catat_aktivitas(request, 'master_prestasi_diubah', 'Kategori prestasi ditambahkan',
                                    f'Kategori "{nama}" (subkategori "Lainnya" dibuat otomatis).', modul='prestasi')
                    messages.success(request, f'Kategori "{nama}" ditambahkan.')

        elif aksi == 'tambah_sub':
            form = MasterSubkategoriForm(request.POST)
            if not form.is_valid():
                pesan_error_form(request, form)
            else:
                nama = form.cleaned_data['nama']
                kat = form.cleaned_data['kategori_id']
                kelompok = form.cleaned_data['kelompok']
                if SubkategoriPrestasi.objects.filter(kategori=kat, kelompok=kelompok, nama__iexact=nama).exists():
                    messages.error(request, 'Subkategori itu sudah ada pada kategori tersebut.')
                else:
                    SubkategoriPrestasi.objects.create(kategori=kat, kelompok=kelompok, nama=nama)
                    catat_aktivitas(request, 'master_prestasi_diubah', 'Subkategori prestasi ditambahkan',
                                    f'"{kelompok + " - " if kelompok else ""}{nama}" pada kategori "{kat.nama}".', modul='prestasi')
                    messages.success(request, f'Subkategori "{nama}" ditambahkan.')

        elif aksi in ('toggle_kategori', 'toggle_sub'):
            model = KategoriPrestasi if aksi == 'toggle_kategori' else SubkategoriPrestasi
            form = MasterAksiForm(request.POST)
            obj = model.objects.filter(pk=form.cleaned_data['id']).first() if form.is_valid() else None
            if obj is None:
                messages.error(request, 'Data tidak ditemukan.')
            else:
                obj.aktif = not obj.aktif
                obj.save(update_fields=['aktif'])
                label = obj.nama
                catat_aktivitas(request, 'master_prestasi_diubah',
                                'Master prestasi ' + ('diaktifkan' if obj.aktif else 'dinonaktifkan'),
                                f'"{label}"', modul='prestasi')
                messages.success(request, f'"{label}" ' + ('diaktifkan.' if obj.aktif else 'dinonaktifkan (prestasi lama tetap utuh).'))

        elif aksi == 'ubah_nama':
            tipe = request.POST.get('tipe')
            model = KategoriPrestasi if tipe == 'kategori' else SubkategoriPrestasi
            form_id, form_nama = MasterAksiForm(request.POST), MasterNamaForm(request.POST)
            if not form_nama.is_valid():
                pesan_error_form(request, form_nama)
            else:
                obj = model.objects.filter(pk=form_id.cleaned_data['id']).first() if form_id.is_valid() else None
                nama = form_nama.cleaned_data['nama']
                if obj is None:
                    messages.error(request, 'Data tidak ditemukan.')
                else:
                    lama = obj.nama
                    obj.nama = nama
                    try:
                        with transaction.atomic():
                            obj.save(update_fields=['nama'])
                    except IntegrityError:
                        messages.error(request, 'Nama itu sudah dipakai.')
                    else:
                        catat_aktivitas(request, 'master_prestasi_diubah', 'Master prestasi diubah nama',
                                        f'"{lama}" -> "{nama}"', modul='prestasi')
                        messages.success(request, 'Nama diperbarui.')
        else:
            messages.error(request, 'Aksi tidak dikenal.')
        return redirect('master_prestasi')

    kategori_list = (
        KategoriPrestasi.objects
        .annotate(jumlah_prestasi=Count('subkategori__prestasi', distinct=True))
        .prefetch_related('subkategori')
        .order_by('urutan', 'nama')
    )
    pemakaian = {
        r['subkategori_id']: r['n']
        for r in Prestasi.objects
        .exclude(subkategori__isnull=True).values('subkategori_id').annotate(n=Count('id'))
    }
    for kat in kategori_list:
        kat.daftar_sub = list(kat.subkategori.all())
        for sub in kat.daftar_sub:
            sub.dipakai = pemakaian.get(sub.pk, 0)
    return render(request, 'eprestasi/master_prestasi/kelola.html', {
        'active_menu': 'master_prestasi',
        'kategori_list': kategori_list,
    })


# ======================================================================
# 11. PERMINTAAN RESET PASSWORD
# ======================================================================


# ===========================================================================
# ADMIN: kelola permintaan reset password
# ===========================================================================
S_PASSWORD_SEMENTARA = 'lp_password_sementara'   # kunci sesi: password sementara hasil reset (tampil sekali)
FILTER_STATUS = ('pending', 'selesai', 'ditolak')


PERMINTAAN_PER_HALAMAN = 25


@role_required('admin', 'super_admin')
def permintaan_reset_list(request):
    status = request.GET.get('status', 'pending').strip()
    if status not in FILTER_STATUS:
        status = 'pending'

    qs = (PermintaanResetPassword.objects.filter(status=status)
          .select_related('siswa', 'siswa__users')[:PERMINTAAN_PER_HALAMAN])
    hitung = {s: PermintaanResetPassword.objects.filter(status=s).count() for s in FILTER_STATUS}

    return render(request, 'eprestasi/permintaan_reset/list.html', {
        'active_menu': 'permintaan_reset',
        'daftar': list(qs),
        'status': status,
        'hitung': hitung,
        'password_sementara': request.session.pop(S_PASSWORD_SEMENTARA, None),
    })


@role_required('admin', 'super_admin')
@require_POST
def permintaan_reset_proses(request, permintaan_id):
    """Reset password siswa ke password sementara acak (ditampilkan SEKALI ke admin)."""
    with transaction.atomic():
        permintaan = get_object_or_404(
            PermintaanResetPassword.objects.select_for_update().select_related('siswa', 'siswa__users'),
            pk=permintaan_id,
        )
        if permintaan.status != 'pending':
            messages.warning(request, 'Permintaan ini sudah diproses sebelumnya.')
            return redirect('permintaan_reset_list')

        siswa = permintaan.siswa
        password = _buat_password_acak(8)
        user = siswa.users
        user.password = make_password(password)
        user.save(update_fields=['password', 'updated_at'])

        permintaan.status = 'selesai'
        permintaan.diproses_pada = timezone.now()
        permintaan.diproses_oleh = request.session.get('username', '')
        permintaan.save(update_fields=['status', 'diproses_pada', 'diproses_oleh'])

    catat_aktivitas(
        request, 'password_direset', 'Admin mereset password siswa (permintaan siswa)',
        f'Password siswa "{siswa.nama or siswa.nis}" (NIS {siswa.nis}) direset atas permintaan siswa.',
        modul='siswa',
    )
    request.session[S_PASSWORD_SEMENTARA] = {
        'nis': siswa.nis, 'nama': siswa.nama or '-', 'password': password,
    }
    messages.success(request, f'Password siswa NIS {siswa.nis} berhasil direset.')
    return redirect('permintaan_reset_list')


@role_required('admin', 'super_admin')
@require_POST
def permintaan_reset_tolak(request, permintaan_id):
    permintaan = get_object_or_404(PermintaanResetPassword.objects.select_related('siswa'), pk=permintaan_id)
    if permintaan.status != 'pending':
        messages.warning(request, 'Permintaan ini sudah diproses sebelumnya.')
        return redirect('permintaan_reset_list')

    permintaan.status = 'ditolak'
    permintaan.diproses_pada = timezone.now()
    permintaan.diproses_oleh = request.session.get('username', '')
    form = CatatanForm(request.POST)
    if not form.is_valid():
        pesan_error_form(request, form)
        return redirect('permintaan_reset_list')
    permintaan.catatan = form.cleaned_data['catatan']
    permintaan.save(update_fields=['status', 'diproses_pada', 'diproses_oleh', 'catatan'])

    catat_aktivitas(
        request, 'password_direset', 'Admin menolak permintaan reset password',
        f'Permintaan reset password siswa NIS {permintaan.siswa.nis} ditolak.',
        modul='siswa',
    )
    messages.success(request, f'Permintaan reset password NIS {permintaan.siswa.nis} ditolak.')
    return redirect('permintaan_reset_list')


# ======================================================================
# 12. AKUN ADMIN & PROFIL ADMIN
# ======================================================================


@role_required('super_admin')
def admin_list(request):
    context = {
        'active_menu': 'admin',
        'admin_list': Users.objects.filter(role__in=['admin', 'super_admin']).order_by('-role', '-id'),
    }
    return render(request, 'eprestasi/admin_akun/list.html', context)


@role_required('super_admin')
def Create_admin(request):
    if request.method == 'POST':
        form = AdminAkunForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            Users.objects.create(
                username=data['username'],
                password=make_password(data['password']),
                role='admin',  # dibuat lewat web selalu 'admin' biasa, bukan super_admin
            )
            catat_aktivitas(
                request, 'akun_dibuat',
                'Super admin menambahkan admin',
                f'Akun admin "{data["username"]}" berhasil dibuat',
                modul='admin',
            )

            messages.success(request, f'Akun admin "{data["username"]}" berhasil dibuat.')
            return redirect('admin_list')
    else:
        form = AdminAkunForm()

    context = {'active_menu': 'admin', 'form': form, 'mode': 'tambah'}
    return render(request, 'eprestasi/admin_akun/form.html', context)


@role_required('super_admin')
def Update_admin(request, admin_id):
    admin_user = get_object_or_404(Users, id=admin_id, role__in=['admin', 'super_admin'])

    if request.method == 'POST':
        form = AdminAkunForm(request.POST, admin_id=admin_user.id)
        if form.is_valid():
            data = form.cleaned_data
            admin_user.username = data['username']
            if data.get('password'):
                admin_user.password = make_password(data['password'])
            admin_user.save()
            catat_aktivitas(
                request, 'akun_diubah', 'Super admin mengubah data admin',
                f'Akun admin "{admin_user.username}" diperbarui.', modul='admin',
            )
            messages.success(request, f'Akun admin "{admin_user.username}" berhasil diperbarui.')
            return redirect('admin_list')
    else:
        form = AdminAkunForm(admin_id=admin_user.id, initial={'username': admin_user.username})

    context = {'active_menu': 'admin', 'form': form, 'mode': 'edit', 'admin_user': admin_user}
    return render(request, 'eprestasi/admin_akun/form.html', context)


@role_required('super_admin')
def delete_admin(request, admin_id):
    admin_user = get_object_or_404(Users, id=admin_id, role__in=['admin', 'super_admin'])

    if request.method == 'POST':
        # Proteksi 1: super_admin tidak bisa dihapus lewat web sama sekali
        # (kalau memang perlu, harus lewat DB/terminal langsung -- keputusan sadar, bukan klik tombol)
        if admin_user.role == 'super_admin':
            messages.error(request, 'Akun super admin tidak bisa dihapus lewat halaman ini.')
            return redirect('admin_list')

        # Proteksi 2: tidak bisa menghapus akun diri sendiri (mencegah kekunci sendiri)
        if admin_user.id == request.session.get('user_id'):
            messages.error(request, 'Anda tidak bisa menghapus akun Anda sendiri.')
            return redirect('admin_list')

        username = admin_user.username
        admin_user.delete()

        catat_aktivitas(
            request, 'akun_dihapus',
            'Super admin menghapus admin',
            f'Akun admin "{username}" telah dihapus',
            modul='admin',
        )

        messages.success(request, f'Akun admin "{username}" telah dihapus.')

    return redirect('admin_list')


@role_required('admin', 'super_admin')
def profil_admin(request):
    user = get_object_or_404(Users, id=request.session.get('user_id'))

    if request.method == 'POST':
        form = AdminGantiPasswordForm(request.POST, user=user)
        if form.is_valid():
            user.password = make_password(form.cleaned_data['password_baru'])
            user.save(update_fields=['password', 'updated_at'])
            # Ganti session key supaya session lama tidak bisa dipakai ulang;
            # user tetap login di browser ini.
            request.session.cycle_key()
            catat_aktivitas(
                request, 'akun_diubah',
                'Admin mengganti password sendiri',
                f'Akun \"{user.username}\" berhasil mengganti password.',
                modul='admin',
            )
            messages.success(request, 'Password berhasil diganti.')
            return redirect('profil_admin')

        # Jejak percobaan gagal hanya bila password lama yang salah.
        if 'password_lama' in form.errors:
            catat_aktivitas(
                request, 'akun_diubah',
                'Percobaan ganti password gagal',
                f'Akun \"{user.username}\" salah memasukkan password saat ini.',
                modul='admin', status_log='gagal',
            )
    else:
        form = AdminGantiPasswordForm(user=user)

    context = {
        'active_menu': 'profil_admin',
        'profil_user': user,
        'form': form,
        'password_min_length': PASSWORD_MIN_LENGTH,
    }
    return render(request, 'eprestasi/admin_akun/profil.html', context)
