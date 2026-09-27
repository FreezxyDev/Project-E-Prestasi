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
    ws.append(['NIS', 'Password (opsional)'])
    ws.append(['10001', 'passwordsiswa1'])
    ws.append(['10002', ''])  # contoh: boleh dikosongkan, nanti di-generate otomatis

    ws.column_dimensions['A'].width = 15
    ws.column_dimensions['B'].width = 25

    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)

    response = HttpResponse(
        buffer.read(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = 'attachment; filename="template_import_siswa.xlsx"'
    return response


def _proses_import_siswa(file_excel):
    """
    Baca file Excel baris per baris, bikin akun siswa buat tiap baris valid.
    Return dict: {'berhasil': [...], 'gagal': [...]}

    Kolom A = NIS (wajib), kolom B = Password (opsional, di-generate otomatis
    kalau kosong). Baris 1 dianggap header, diabaikan.
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
        Siswa.objects.create(users=user_account, nis=nis, status='aktif')

        berhasil.append({'baris': baris_ke, 'nis': nis, 'username': username, 'password': password})

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