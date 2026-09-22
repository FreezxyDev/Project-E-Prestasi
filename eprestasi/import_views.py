import io
import secrets
import string

import openpyxl
from django.contrib import messages
from django.contrib.auth.hashers import make_password
from django.http import HttpResponse
from django.shortcuts import render, redirect

from .decorators import role_required
from .forms import ImportSiswaForm
from .models import Siswa, Users
from .views import _generate_username  # reuse -- jangan duplikat logic-nya di sini

# Dipakai buat mencocokkan isi kolom Kelas/Jurusan di Excel (bebas huruf besar/kecil,
# spasi nyasar di ujung) terhadap pilihan resmi di model Siswa.
_KELAS_VALID = {label.strip().lower(): value for value, label in Siswa.KELAS_CHOICES}
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
    kelas_list = [label for _, label in Siswa.KELAS_CHOICES]
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


def _proses_import_siswa(file_excel):
    """
    Baca file Excel baris per baris, bikin akun siswa buat tiap baris valid.
    Return dict: {'berhasil': [...], 'gagal': [...]}

    Kolom: A=NIS (wajib), B=Password (opsional), C=Nama (opsional),
    D=Kelas (opsional), E=Jurusan (opsional). Baris 1 dianggap header, diabaikan.

    Nama/Kelas/Jurusan diisi langsung ke akun siswa kalau ada di file -- jadi
    pas siswa pertama kali buka halaman "Lengkapi Profil", field itu SUDAH
    keisi otomatis dan siswa tinggal melengkapi sisanya (email, no HP, foto).
    """
    berhasil = []
    gagal = []

    try:
        wb = openpyxl.load_workbook(file_excel, read_only=True, data_only=True)
        ws = wb.active
    except Exception:
        return {'berhasil': [], 'gagal': [], 'error_file': 'File tidak bisa dibaca. Pastikan formatnya .xlsx yang valid (bukan .xls atau .csv).'}

    nis_dipakai_di_file = set()  # jaga-jaga ada NIS kembar DALAM 1 file yang sama

    for baris_ke, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        if not row or row[0] is None or str(row[0]).strip() == '':
            continue  # baris kosong, lewati saja (jangan dianggap error)

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

        kelas_value, kelas_cocok = _cocokkan_pilihan(kelas_mentah, _KELAS_VALID)
        jurusan_value, jurusan_cocok = _cocokkan_pilihan(jurusan_mentah, _JURUSAN_VALID)

        if nis in nis_dipakai_di_file:
            gagal.append({'baris': baris_ke, 'nis': nis, 'alasan': 'NIS dobel di dalam file ini'})
            continue

        if Siswa.objects.filter(nis=nis).exists():
            gagal.append({'baris': baris_ke, 'nis': nis, 'alasan': 'NIS sudah terdaftar di sistem'})
            continue

        nis_dipakai_di_file.add(nis)
        password = password_dari_file or _buat_password_acak()
        username = _generate_username(nis)

        user_account = Users.objects.create(
            username=username,
            password=make_password(password),
            role='siswa',
        )
        Siswa.objects.create(
            users=user_account,
            nis=nis,
            status='aktif',
            nama=nama_dari_file,
            kelas=kelas_value,
            jurusan=jurusan_value,
        )

        # Catatan kalau Kelas/Jurusan di file tidak cocok pilihan resmi --
        # akun TETAP dibuat, kolom itu cuma dikosongkan (siswa isi manual nanti).
        catatan = []
        if kelas_mentah and not kelas_cocok:
            catatan.append(f"Kelas '{kelas_mentah}' tidak dikenali, dikosongkan")
        if jurusan_mentah and not jurusan_cocok:
            catatan.append(f"Jurusan '{jurusan_mentah}' tidak dikenali, dikosongkan")

        berhasil.append({
            'baris': baris_ke,
            'nis': nis,
            'username': username,
            'password': password,
            'nama': nama_dari_file,
            'kelas': kelas_value or '',
            'jurusan': jurusan_value or '',
            'catatan': '; '.join(catatan),
        })

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

    context = {'form': form, 'active_menu': 'siswa'}
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