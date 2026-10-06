"""
Pengelolaan Kelas & Riwayat Kelas Siswa
========================================
Prinsip utama (lihat models.py untuk penjelasan lebih lengkap):
- Jurusan siswa bersifat TETAP, ditentukan saat data siswa dibuat.
- Kelas siswa BISA BERUBAH setiap tahun ajaran, sehingga TIDAK disimpan
  cukup sebagai satu kolom di data siswa. Kondisi kelas siswa pada tiap
  tahun ajaran disimpan di RiwayatKelas, dan setiap kejadian penempatan
  atau perubahan kelas dicatat permanen (append-only) di LogPerubahanKelas.
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
import re

from django.db.models import Q, Count
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.utils import timezone

from .models import (
    Siswa, Users, Tahun_ajaran, Kelas, RiwayatKelas, LogPerubahanKelas,
    DAFTAR_JURUSAN, DAFTAR_TINGKAT, TINGKAT_KE_ROMAWI,
)
from .forms import KelasForm, BuatKelasMassalForm, SalinKelasForm, NaikkanOtomatisForm
from .decorators import role_required


# =========================================================
# HELPER
# =========================================================

def _tahun_ajaran_terpilih(request, param='tahun_ajaran'):
    """
    Ambil Tahun_ajaran dari query/POST param (by id). Kalau tidak ada atau
    tidak valid, jatuhkan ke tahun ajaran yang sedang aktif.
    """
    nilai = request.GET.get(param) or request.POST.get(param)
    tahun = None
    if nilai:
        tahun = Tahun_ajaran.objects.filter(id=nilai).first()
    if not tahun:
        tahun = Tahun_ajaran.objects.filter(status='aktif').first()
    return tahun


def _admin_saat_ini(request):
    user_id = request.session.get('user_id')
    if not user_id:
        return None
    return Users.objects.filter(id=user_id).first()


def _redirect_pengelolaan_kelas(tahun_ajaran=None, **extra_params):
    from django.urls import reverse
    params = {}
    if tahun_ajaran:
        params['tahun_ajaran'] = tahun_ajaran.id
    params.update({k: v for k, v in extra_params.items() if v not in (None, '')})
    query = '&'.join(f'{k}={v}' for k, v in params.items())
    url = reverse('pengelolaan_kelas')
    return redirect(f'{url}?{query}' if query else url)


# =========================================================
# HALAMAN UTAMA: PENGELOLAAN KELAS
# =========================================================

@role_required('admin', 'super_admin')
def pengelolaan_kelas(request):
    tahun_ajaran_terpilih = _tahun_ajaran_terpilih(request)
    daftar_tahun_ajaran = Tahun_ajaran.objects.all().order_by('-id')

    jurusan_filter = request.GET.get('jurusan', '')
    tingkat_filter = request.GET.get('tingkat', '')
    kelas_filter = request.GET.get('kelas', '')
    q = request.GET.get('q', '').strip()

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
        'daftar_jurusan': DAFTAR_JURUSAN,
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

    tahun_ajaran = get_object_or_404(Tahun_ajaran, id=request.POST.get('tahun_ajaran'))
    kelas_tujuan_id = request.POST.get('kelas_tujuan')
    siswa_ids = request.POST.getlist('siswa_ids')
    jenis_perubahan = request.POST.get('jenis_perubahan') or 'penempatan_awal'
    mode_manual_xii = request.POST.get('mode_manual_xii') == '1'
    alasan_perubahan = request.POST.get('alasan_perubahan', '').strip()

    filter_balik = {
        'jurusan': request.POST.get('balik_jurusan', ''),
        'tingkat': request.POST.get('balik_tingkat', ''),
        'kelas': request.POST.get('balik_kelas', ''),
        'q': request.POST.get('balik_q', ''),
    }

    if not kelas_tujuan_id:
        messages.error(request, 'Pilih kelas tujuan terlebih dahulu.')
        return _redirect_pengelolaan_kelas(tahun_ajaran, **filter_balik)

    if not siswa_ids:
        messages.error(request, 'Pilih minimal satu siswa yang akan ditempatkan.')
        return _redirect_pengelolaan_kelas(tahun_ajaran, **filter_balik)

    kelas_tujuan = get_object_or_404(Kelas, id=kelas_tujuan_id, tahun_ajaran=tahun_ajaran)

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

    admin_user = _admin_saat_ini(request)
    berhasil = 0
    sudah_di_kelas = 0
    ditolak = []

    for sid in siswa_ids:
        siswa = Siswa.objects.filter(id=sid, status='aktif').first()
        if not siswa:
            continue

        # Aturan #2-7 & #17: jurusan siswa harus sama dengan jurusan kelas tujuan.
        if siswa.jurusan != kelas_tujuan.jurusan:
            ditolak.append(f'{siswa.nama} (jurusan {siswa.jurusan or "-"})')
            continue

        riwayat_lama = RiwayatKelas.objects.filter(siswa=siswa, tahun_ajaran=tahun_ajaran).first()
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
    tahun = get_object_or_404(Tahun_ajaran, id=request.POST.get('tahun_ajaran'))

    daftar_nis, dilihat = [], set()
    for token in re.split(r'[\s,;]+', request.POST.get('nis_list', '')):
        token = token.strip()
        if token.endswith('.0') and token[:-2].isdigit():   # NIS dari Excel bisa berakhiran .0
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

    tahun_ajaran_tujuan = get_object_or_404(Tahun_ajaran, id=request.POST.get('tahun_ajaran'))
    form = NaikkanOtomatisForm(request.POST)

    if not form.is_valid():
        messages.error(request, 'Data kenaikan kelas otomatis tidak valid. Pilih tahun ajaran asal.')
        return _redirect_pengelolaan_kelas(tahun_ajaran_tujuan)

    tahun_ajaran_asal = form.cleaned_data['tahun_ajaran_asal']
    jurusan = form.cleaned_data.get('jurusan')

    if tahun_ajaran_asal.id == tahun_ajaran_tujuan.id:
        messages.error(request, 'Tahun ajaran asal dan tujuan tidak boleh sama.')
        return _redirect_pengelolaan_kelas(tahun_ajaran_tujuan)

    riwayat_asal_qs = RiwayatKelas.objects.filter(
        tahun_ajaran=tahun_ajaran_asal, tingkat=11, siswa__status='aktif'
    ).select_related('siswa', 'kelas')
    if jurusan:
        riwayat_asal_qs = riwayat_asal_qs.filter(siswa__jurusan=jurusan)

    admin_user = _admin_saat_ini(request)
    naik = 0

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


# =========================================================
# KELOLA DAFTAR KELAS
# =========================================================

@role_required('admin', 'super_admin')
def kelola_kelas(request):
    tahun_ajaran_terpilih = _tahun_ajaran_terpilih(request)
    daftar_tahun_ajaran = Tahun_ajaran.objects.all().order_by('-id')

    daftar_kelas = []
    if tahun_ajaran_terpilih:
        daftar_kelas = Kelas.objects.filter(tahun_ajaran=tahun_ajaran_terpilih).order_by('jurusan', 'tingkat', 'nama_kelas')

    context = {
        'active_menu': 'pengelolaan_kelas',
        'daftar_tahun_ajaran': daftar_tahun_ajaran,
        'tahun_ajaran_terpilih': tahun_ajaran_terpilih,
        'daftar_kelas': daftar_kelas,
        'form_kelas': KelasForm(tahun_ajaran=tahun_ajaran_terpilih),
        'form_massal': BuatKelasMassalForm(tahun_ajaran=tahun_ajaran_terpilih),
        'form_salin': SalinKelasForm(),
    }
    return render(request, 'eprestasi/pengelolaan_kelas/kelola_kelas.html', context)


@role_required('admin', 'super_admin')
def tambah_kelas(request):
    if request.method != 'POST':
        return redirect('kelola_kelas')

    tahun_ajaran = get_object_or_404(Tahun_ajaran, id=request.POST.get('tahun_ajaran'))
    form = KelasForm(request.POST, tahun_ajaran=tahun_ajaran)

    if form.is_valid():
        data = form.cleaned_data
        Kelas.objects.create(
            nama_kelas=data['nama_kelas'],
            jurusan=data['jurusan'],
            tingkat=data['tingkat'],
            tahun_ajaran=tahun_ajaran,
        )
        messages.success(request, f'Kelas "{data["nama_kelas"]}" berhasil ditambahkan.')
    else:
        for field, errors in form.errors.items():
            for error in errors:
                messages.error(request, error)

    return redirect(f'/pengelolaan-kelas/kelas/?tahun_ajaran={tahun_ajaran.id}')


@role_required('admin', 'super_admin')
def buat_kelas_massal(request):
    if request.method != 'POST':
        return redirect('kelola_kelas')

    tahun_ajaran = get_object_or_404(Tahun_ajaran, id=request.POST.get('tahun_ajaran'))
    form = BuatKelasMassalForm(request.POST, tahun_ajaran=tahun_ajaran)

    if form.is_valid():
        data = form.cleaned_data
        jurusan = data['jurusan']
        tingkat = int(data['tingkat'])
        romawi = TINGKAT_KE_ROMAWI.get(tingkat, '')
        dibuat = 0
        for nomor in range(1, data['jumlah_kelas'] + 1):
            nama_kelas = f'{romawi} {jurusan} {nomor}'
            _kelas, is_baru = Kelas.objects.get_or_create(
                nama_kelas=nama_kelas, tahun_ajaran=tahun_ajaran,
                defaults={'jurusan': jurusan, 'tingkat': tingkat}
            )
            if is_baru:
                dibuat += 1
        messages.success(request, f'{dibuat} kelas baru berhasil dibuat untuk jurusan {jurusan}.')
    else:
        for field, errors in form.errors.items():
            for error in errors:
                messages.error(request, error)

    return redirect(f'/pengelolaan-kelas/kelas/?tahun_ajaran={tahun_ajaran.id}')


@role_required('admin', 'super_admin')
def salin_kelas(request):
    if request.method != 'POST':
        return redirect('kelola_kelas')

    tahun_ajaran_tujuan = get_object_or_404(Tahun_ajaran, id=request.POST.get('tahun_ajaran'))
    form = SalinKelasForm(request.POST)

    if form.is_valid():
        sumber = form.cleaned_data['tahun_ajaran_sumber']
        dibuat = 0
        for kelas in Kelas.objects.filter(tahun_ajaran=sumber):
            _obj, is_baru = Kelas.objects.get_or_create(
                nama_kelas=kelas.nama_kelas, tahun_ajaran=tahun_ajaran_tujuan,
                defaults={'jurusan': kelas.jurusan, 'tingkat': kelas.tingkat}
            )
            if is_baru:
                dibuat += 1
        messages.success(
            request,
            f'{dibuat} kelas berhasil disalin dari tahun ajaran {sumber.tahun_ajaran}.'
        )
    else:
        messages.error(request, 'Pilih tahun ajaran sumber yang valid.')

    return redirect(f'/pengelolaan-kelas/kelas/?tahun_ajaran={tahun_ajaran_tujuan.id}')


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
            return redirect(f'/pengelolaan-kelas/kelas/?tahun_ajaran={tahun_ajaran_id}')
    return redirect(f'/pengelolaan-kelas/kelas/?tahun_ajaran={kelas.tahun_ajaran_id}')


# =========================================================
# RIWAYAT KELAS SISWA (per siswa)
# =========================================================

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


# =========================================================
# RIWAYAT BERDASARKAN KELAS
# =========================================================

@role_required('admin', 'super_admin')
def riwayat_berdasarkan_kelas(request):
    tahun_ajaran_terpilih = _tahun_ajaran_terpilih(request)
    daftar_tahun_ajaran = Tahun_ajaran.objects.all().order_by('-id')

    jurusan_filter = request.GET.get('jurusan', '')
    kelas_id = request.GET.get('kelas', '')

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
            daftar_riwayat = (
                RiwayatKelas.objects.filter(kelas=kelas_terpilih)
                .select_related('siswa')
                .order_by('siswa__nama')
            )
            # Lengkapi "perjalanan siswa" (seluruh riwayat kelasnya, urut lama -> baru)
            for r in daftar_riwayat:
                r.perjalanan = list(
                    RiwayatKelas.objects.filter(siswa=r.siswa)
                    .select_related('kelas', 'tahun_ajaran')
                    .order_by('tahun_ajaran_id')
                )

    context = {
        'active_menu': 'pengelolaan_kelas',
        'daftar_tahun_ajaran': daftar_tahun_ajaran,
        'tahun_ajaran_terpilih': tahun_ajaran_terpilih,
        'daftar_jurusan': DAFTAR_JURUSAN,
        'jurusan_filter': jurusan_filter,
        'daftar_kelas': daftar_kelas,
        'kelas_id': kelas_id,
        'kelas_terpilih': kelas_terpilih,
        'daftar_riwayat': daftar_riwayat,
    }
    return render(request, 'eprestasi/pengelolaan_kelas/riwayat_kelas.html', context)


# =========================================================
# LOG PERUBAHAN KELAS (jejak audit)
# =========================================================

@role_required('admin', 'super_admin')
def log_perubahan_kelas(request):
    q = request.GET.get('q', '').strip()
    tahun_ajaran_id = request.GET.get('tahun_ajaran', '')

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