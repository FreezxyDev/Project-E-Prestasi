from django import forms
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.urls import reverse
from django.contrib import messages
from django.contrib.auth.hashers import make_password, check_password
from django.db.models import Q, Count
from django.utils import timezone
from datetime import timedelta
import json

from .models import Users, Siswa, Kesiswaan, Tahun_ajaran, Prestasi, LogAktivitas
from .forms import SiswaAkunForm, KesiswaanAkunForm, TahunAjaranForm, AdminAkunForm
from .decorators import role_required
from .log_utils import catat_aktivitas
from .kelas_utils import tempatkan_ke_kelas, kelas_siswa_aktif


def landing_page(request):
    """Halaman landing page (awal) aplikasi e-prestasi."""
    return render(request, 'eprestasi/landing_page.html')


def cari_siswa_api(request):
    """
    API PUBLIK untuk section "Cari Siswa" di landing page (tanpa login).
    Mencari akun siswa sungguhan berdasarkan NIS atau nama, lalu mengembalikan
    link ke halaman portofolio publik mereka.

    Sengaja hanya mengembalikan data yang memang sudah tampil di portofolio
    publik (NIS, nama, kelas, jurusan, jumlah prestasi terverifikasi) -- tidak ada
    email/no HP/alamat. Query minimal 3 karakter dan hasil dibatasi, supaya
    daftar siswa tidak bisa diambil sekaligus lewat pencarian satu huruf.
    """
    q = request.GET.get('q', '').strip()
    if len(q) < 3:
        return JsonResponse({'results': [], 'terlalu_pendek': True})

    siswa_qs = (
        Siswa.objects
        .filter(status__in=['aktif', 'alumni'])
        .filter(Q(nis__icontains=q) | Q(nama__icontains=q))
        .annotate(total_prestasi=Count('prestasi', filter=Q(prestasi__status='diterima')))
        .order_by('nama', 'nis')[:12]
    )
    results = [
        {
            'nis': s.nis,
            'nama': s.nama or s.nis,
            'kelas': s.kelas or '-',
            'jurusan': s.jurusan or '-',
            'alumni': s.status == 'alumni',
            'prestasi': s.total_prestasi,
            'url': reverse('portofolio_publik', args=[s.nis]),
        }
        for s in siswa_qs
    ]
    return JsonResponse({'results': results, 'terlalu_pendek': False})


def _generate_username(identifier):
    """
    Username akun dibuat otomatis dari NIS (siswa) / NIP (kesiswaan).
    Jika identifier tersebut ternyata sudah dipakai sebagai username (kasus langka,
    misal re-use NIS/NIP lama), tambahkan suffix angka supaya tetap unik.
    """
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
    """
    naik, lulus = 0, 0
    for siswa in Siswa.objects.filter(status='aktif'):
        if siswa.tingkat < 10:
            siswa.tingkat = 10
            
        if siswa.tingkat >= 12:
            siswa.status = 'alumni'
            lulus += 1
        else:
            siswa.tingkat += 1
            naik += 1
        siswa.save(update_fields=['tingkat', 'status'])
    return naik, lulus


# =========================================================
# DASHBOARD
# =========================================================

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
    for p in Prestasi.objects.filter(tanggal_upload__date__gte=start):
        tgl = timezone.localtime(p.tanggal_upload).date()
        if tgl in per_hari:
            per_hari[tgl] += 1
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


# =========================================================
# CRUD SISWA
# =========================================================

@role_required('admin', 'super_admin')
def siswa_list(request):
    status_filter = request.GET.get('status', '')
    q = request.GET.get('q', '')

    siswa_qs = Siswa.objects.select_related('users').all()

    if status_filter in ('aktif', 'alumni'):
        siswa_qs = siswa_qs.filter(status=status_filter)

    if q:
        siswa_qs = siswa_qs.filter(
            Q(nama__icontains=q) | Q(nis__icontains=q) | Q(kelas__icontains=q)
        )

    siswa_qs = siswa_qs.order_by('-id')

    context = {
        'active_menu': 'siswa',
        'siswa_list': siswa_qs,
        'status_filter': status_filter,
        'q': q,
        'total_aktif': Siswa.objects.filter(status='aktif').count(),
        'total_alumni': Siswa.objects.filter(status='alumni').count(),
    }
    return render(request, 'eprestasi/kelola_user/list.html', context)


@role_required('admin', 'super_admin')
def Create_siswa(request):
    if request.method == 'POST':
        form = SiswaAkunForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            username = _generate_username(data['nis'])

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
                Users.objects.filter(id=request.session.get('user_id')).first(),
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
            if siswa.status != (data.get('status') or siswa.status):
                perubahan.append(f'status {siswa.status} → {data.get("status")}')

            siswa.nis = data['nis']
            siswa.nama = data['nama']
            siswa.jurusan = data.get('jurusan', '')
            if data.get('status'):
                siswa.status = data['status']
            siswa.save()

            # Perubahan kelas ditulis ke RiwayatKelas tahun ajaran aktif + log perubahan;
            # Siswa.kelas/tingkat ikut disinkronkan oleh helper.
            if kelas_obj:
                tempatkan_ke_kelas(
                    siswa, kelas_obj,
                    Users.objects.filter(id=request.session.get('user_id')).first(),
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


# =========================================================
# CRUD KESISWAAN
# =========================================================

@role_required('admin', 'super_admin')
def kesiswaan_list(request):
    context = {
        'active_menu': 'kesiswaan',
        'kesiswaan_list': Kesiswaan.objects.select_related('user').all().order_by('-id'),
    }
    return render(request, 'eprestasi/kelola_user/list.html', context)


@role_required('admin', 'super_admin')
def Create_kesiswaan(request):
    if request.method == 'POST':
        form = KesiswaanAkunForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
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


# =========================================================
# CRUD TAHUN AJARAN
# =========================================================

@role_required('admin', 'super_admin')
def tahun_ajaran_list(request):
    q = request.GET.get('q', '').strip()
    sort = request.GET.get('sort', 'terbaru')

    daftar = Tahun_ajaran.objects.all()
    if q:
        daftar = daftar.filter(tahun_ajaran__icontains=q)

    sort_map = {
        'nama_asc': 'tahun_ajaran',
        'nama_desc': '-tahun_ajaran',
        'terbaru': '-id',
        'terlama': 'id',
    }
    daftar = daftar.order_by(sort_map.get(sort, '-id'))

    # ---- Statistik Prestasi ----
    # Kalau ada filter nama (q), statistik prestasi cuma menghitung punya
    # tahun ajaran yang cocok dengan filter. Kalau filter kosong -> otomatis
    # menghitung SEMUA tahun ajaran (aktif & nonaktif).
    prestasi_qs = Prestasi.objects.all()
    if q:
        prestasi_qs = prestasi_qs.filter(tahun_ajaran__tahun_ajaran__icontains=q)

    statistik_prestasi = {
        'total': prestasi_qs.count(),
        'diterima': prestasi_qs.filter(status='diterima').count(),
        'pending': prestasi_qs.filter(status='pending').count(),
        'perbaikan': prestasi_qs.filter(status='perbaikan').count(),
        'ditolak': prestasi_qs.filter(status='ditolak').count(),
    }

    # ---- Statistik Akun ----
    # CATATAN: tabel Siswa/Kesiswaan tidak punya relasi ke Tahun_ajaran, jadi
    # jumlah akun selalu dihitung dari SELURUH sistem (tidak ikut terfilter
    # oleh pencarian nama tahun ajaran).
    statistik_akun = {
        'siswa_aktif': Siswa.objects.filter(status='aktif').count(),
        'siswa_alumni': Siswa.objects.filter(status='alumni').count(),
        'kesiswaan': Kesiswaan.objects.count(),
    }
    statistik_akun['total'] = (
        statistik_akun['siswa_aktif'] + statistik_akun['siswa_alumni'] + statistik_akun['kesiswaan']
    )

    context = {
        'active_menu': 'tahun_ajaran',
        'tahun_ajaran_list': daftar,
        'q': q,
        'sort': sort,
        'statistik_prestasi': statistik_prestasi,
        'statistik_akun': statistik_akun,
        'sedang_difilter': bool(q),
        'total_tahun_ajaran': Tahun_ajaran.objects.count(),
        'tahun_ajaran_aktif': Tahun_ajaran.objects.filter(status='aktif').first(),
        'form_tambah': TahunAjaranForm(initial={'status': 'nonaktif'}),
    }
    return render(request, 'eprestasi/tahun_ajaran/list.html', context)


@role_required('admin', 'super_admin')
def Create_tahun_ajaran(request):
    if request.method == 'POST':
        form = TahunAjaranForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            jadi_aktif = data['status'] == 'aktif'

            if jadi_aktif:
                Tahun_ajaran.objects.filter(status='aktif').update(status='nonaktif')

            Tahun_ajaran.objects.create(
                tahun_ajaran=data['tahun_ajaran'],
                status=data['status'],
            )

            if jadi_aktif:
                naik, lulus = _naikkan_kelas_siswa_aktif()
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
        form = TahunAjaranForm(request.POST)
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


# =========================================================
# KELOLA ADMIN (hanya super_admin)
# =========================================================
# Perhatikan: role_required di sini HANYA 'super_admin', tidak ada 'admin'.
# Jadi walaupun admin biasa berhasil login, dia tetap tidak bisa buka
# menu-menu di bawah ini -- akan dilempar balik ke halaman login.

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


# =========================================================
# PROFIL ADMIN (admin & super_admin)
# =========================================================
# Lihat identitas akun yang sedang login (username, role, tanggal dibuat)
# dan ganti password sendiri. Username hanya bisa DILIHAT di sini --
# perubahan akun admin lain tetap lewat menu Kelola Admin (super_admin).

PASSWORD_MIN_LENGTH = 8


class AdminGantiPasswordForm(forms.Form):
    password_lama = forms.CharField(
        label='Password saat ini',
        widget=forms.PasswordInput(attrs={
            'class': 'form-control', 'autocomplete': 'current-password',
            'placeholder': 'Masukkan password saat ini',
        }),
    )
    password_baru = forms.CharField(
        label='Password baru',
        widget=forms.PasswordInput(attrs={
            'class': 'form-control', 'autocomplete': 'new-password',
            'placeholder': f'Minimal {PASSWORD_MIN_LENGTH} karakter',
        }),
    )
    konfirmasi_password = forms.CharField(
        label='Konfirmasi password baru',
        widget=forms.PasswordInput(attrs={
            'class': 'form-control', 'autocomplete': 'new-password',
            'placeholder': 'Ulangi password baru',
        }),
    )

    def __init__(self, *args, user, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_password_lama(self):
        lama = self.cleaned_data['password_lama']
        if not check_password(lama, self.user.password):
            raise forms.ValidationError('Password saat ini salah.')
        return lama

    def clean_password_baru(self):
        baru = self.cleaned_data['password_baru']
        if len(baru) < PASSWORD_MIN_LENGTH:
            raise forms.ValidationError(f'Password baru minimal {PASSWORD_MIN_LENGTH} karakter.')
        if baru.lower() == self.user.username.lower():
            raise forms.ValidationError('Password baru tidak boleh sama dengan username.')
        return baru

    def clean(self):
        data = super().clean()
        lama, baru, konfirmasi = (
            data.get('password_lama'), data.get('password_baru'), data.get('konfirmasi_password'),
        )
        if baru and konfirmasi and baru != konfirmasi:
            self.add_error('konfirmasi_password', 'Konfirmasi password tidak cocok.')
        if lama and baru and lama == baru:
            self.add_error('password_baru', 'Password baru harus berbeda dari password saat ini.')
        return data


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