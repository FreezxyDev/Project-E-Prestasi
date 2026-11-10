import io
import logging
import secrets
import string

import openpyxl
from django.contrib import messages
from django.contrib.auth.hashers import make_password
from django.db import transaction
from django.http import HttpResponse, JsonResponse
from django.views.decorators.http import require_POST
from django.shortcuts import render, redirect

from .decorators import role_required
from .forms import ImportSiswaForm
from .models import Siswa, Users, Kelas
from .kelas_utils import tahun_ajaran_aktif, tempatkan_ke_kelas
from .views import _generate_username  # reuse -- jangan duplikat logic-nya di sini

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

    nis = str(row[0]).strip()
    # openpyxl bisa balikin angka NIS sebagai float (misal 10001.0) kalau
    # kolomnya keformat "Number" di Excel -- rapikan biar jadi "10001" bukan "10001.0"
    if nis.endswith('.0'):
        nis = nis[:-2]

    password_dari_file = None
    if len(row) > 1 and row[1] is not None and str(row[1]).strip() != '':
        password_dari_file = str(row[1]).strip()

    nama_dari_file = ''
    if len(row) > 2 and row[2] is not None and str(row[2]).strip() != '':
        nama_dari_file = str(row[2]).strip()

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
            kolom = [None if v is None else str(v) for v in list(row)[:5]]
            kolom += [None] * (5 - len(kolom))
            hasil.append([baris_ke, kolom])
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


# =========================================================
# IMPORT DENGAN PROGRES (popup + progress bar, diproses per batch)
# =========================================================
# Alur: browser kirim file ke /mulai/ (file dibaca, baris disimpan di session), lalu memanggil
# /proses/ berulang -- tiap panggilan membuat akun untuk BATCH_BARIS baris dan mengembalikan
# persentase. Proses digerakkan oleh browser: kalau halaman ditutup, sisa baris TIDAK diproses
# (akun yang sudah terbuat tetap ada dan kredensialnya bisa dilihat di halaman hasil).

BATCH_BARIS = 10
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
        pesan = ' '.join(e for errs in form.errors.values() for e in errs) or 'File tidak valid.'
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
    if posisi_klien is not None and posisi_klien.isdigit() and int(posisi_klien) != job['posisi']:
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