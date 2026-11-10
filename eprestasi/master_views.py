"""
Pengelolaan kategori & subkategori prestasi (khusus Admin & Super Admin)
=========================================================================
Kategori dan subkategori bisa ditambah/diubah/dinonaktifkan tanpa ubah kode.
Tidak ada hapus permanen: data yang sudah dipakai prestasi tidak boleh hilang, jadi
yang tersedia hanya "nonaktifkan" (tidak muncul lagi di form pengajuan baru).
"""
from django.contrib import messages
from django.db import transaction
from django.db.models import Count
from django.shortcuts import render, redirect, get_object_or_404
from django.utils.text import slugify
from django.views.decorators.http import require_http_methods

from .decorators import role_required
from .log_utils import catat_aktivitas
from .models import KategoriPrestasi, SubkategoriPrestasi, Prestasi


# ==========================================
# KATEGORI & SUBKATEGORI
# ==========================================

@role_required('admin', 'super_admin')
@require_http_methods(['GET', 'POST'])
def master_prestasi(request):
    if request.method == 'POST':
        aksi = request.POST.get('aksi', '')
        nama = ' '.join(request.POST.get('nama', '').split())

        if aksi == 'tambah_kategori':
            if not nama or len(nama) > 100:
                messages.error(request, 'Nama kategori wajib diisi (maksimal 100 karakter).')
            else:
                kode = slugify(nama)[:50]
                if not kode or KategoriPrestasi.objects.filter(kode=kode).exists():
                    messages.error(request, 'Kategori dengan nama itu sudah ada.')
                else:
                    urutan = (KategoriPrestasi.objects.count() + 1)
                    kat = KategoriPrestasi.objects.create(kode=kode, nama=nama, urutan=urutan)
                    SubkategoriPrestasi.objects.create(kategori=kat, nama='Lainnya', adalah_lainnya=True, urutan=999)
                    catat_aktivitas(request, 'master_prestasi_diubah', 'Kategori prestasi ditambahkan',
                                    f'Kategori "{nama}" (subkategori "Lainnya" dibuat otomatis).', modul='prestasi')
                    messages.success(request, f'Kategori "{nama}" ditambahkan.')

        elif aksi == 'tambah_sub':
            kat = KategoriPrestasi.objects.filter(pk=request.POST.get('kategori_id')).first()
            kelompok = ' '.join(request.POST.get('kelompok', '').split())[:100]
            if kat is None or not nama or len(nama) > 100:
                messages.error(request, 'Pilih kategori dan isi nama subkategori (maksimal 100 karakter).')
            elif SubkategoriPrestasi.objects.filter(kategori=kat, kelompok=kelompok, nama__iexact=nama).exists():
                messages.error(request, 'Subkategori itu sudah ada pada kategori tersebut.')
            else:
                SubkategoriPrestasi.objects.create(kategori=kat, kelompok=kelompok, nama=nama)
                catat_aktivitas(request, 'master_prestasi_diubah', 'Subkategori prestasi ditambahkan',
                                f'"{kelompok + " - " if kelompok else ""}{nama}" pada kategori "{kat.nama}".', modul='prestasi')
                messages.success(request, f'Subkategori "{nama}" ditambahkan.')

        elif aksi in ('toggle_kategori', 'toggle_sub'):
            model = KategoriPrestasi if aksi == 'toggle_kategori' else SubkategoriPrestasi
            obj = model.objects.filter(pk=request.POST.get('id')).first()
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
            obj = model.objects.filter(pk=request.POST.get('id')).first()
            if obj is None or not nama or len(nama) > 100:
                messages.error(request, 'Nama wajib diisi (maksimal 100 karakter).')
            else:
                lama = obj.nama
                obj.nama = nama
                try:
                    with transaction.atomic():
                        obj.save(update_fields=['nama'])
                except Exception:
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
