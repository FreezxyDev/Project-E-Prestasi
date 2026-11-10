"""
Tes otomatis fitur prestasi: form, alur verifikasi, hak akses, rekap, dan ekspor setelah filter/pencarian.

Jalankan (SQLite di memori, TIDAK menyentuh database Supabase):
    python manage.py test eprestasi --settings=config.settings_test
"""
import datetime
import io
from importlib import import_module
from unittest import mock

from django.apps import apps
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from . import prestasi_utils
from .forms import PrestasiUploadForm, PrestasiEditForm
from .models import (
    Users, Siswa, Kesiswaan, Tahun_ajaran, Prestasi, Sertifikat,
    KategoriPrestasi, SubkategoriPrestasi, NotifikasiSiswa,
)


def isi_data_master():
    """Menjalankan seed yang sama dengan migrasi 0032 (tes memakai skema dari model langsung)."""
    modul = import_module('eprestasi.migrations.0032_seed_kategori_prestasi')
    modul.isi_data_awal(apps, None)


def buat_siswa(nis='1001', nama='Budi', kelas='XI RPL 1'):
    user = Users.objects.create(username=f'siswa{nis}', password='x', role='siswa')
    return Siswa.objects.create(
        users=user, nis=nis, nama=nama, kelas=kelas, jurusan='RPL', email=f'{nis}@x.id',
        no_hp='0811', alamat='Bandung', status='aktif', tingkat=11,
    )


def buat_kesiswaan(nip='9001', nama='Pak Kes'):
    user = Users.objects.create(username=f'kes{nip}', password='x', role='kesiswaan')
    return Kesiswaan.objects.create(user=user, nama=nama, nip=nip, no_hp='0822', jabatan='Wakil Kesiswaan')


def masuk(client, user):
    sesi = client.session
    sesi['user_id'] = user.id
    sesi['username'] = user.username
    sesi['role'] = user.role
    sesi.save()


class DasarTes(TestCase):
    def setUp(self):
        isi_data_master()
        self.ta = Tahun_ajaran.objects.create(tahun_ajaran='2026/2027', status='aktif')
        self.siswa = buat_siswa()
        self.kes = buat_kesiswaan()
        self.sub_mtk = SubkategoriPrestasi.objects.get(nama='Matematika', kelompok='Olimpiade Sains')
        self.sub_futsal = SubkategoriPrestasi.objects.get(nama='Futsal')
        self.sub_lain_akad = SubkategoriPrestasi.objects.get(kategori__kode='akademik', adalah_lainnya=True)

    def buat_prestasi(self, **kw):
        data = dict(
            siswa=self.siswa, tahun_ajaran=self.ta, nama_prestasi='Olimpiade Matematika',
            tanggal_prestasi=datetime.date(2026, 9, 1), penyelenggara='Kemendikbud',
            tingkat_prestasi='nasional', wilayah_prestasi='dalam_negeri', deskripsi='x',
            kategori_prestasi='akademik', subkategori=self.sub_mtk, jenis_perolehan='juara_1',
            status='pending', tautan_pendukung='https://contoh.id/hasil',
        )
        data.update(kw)
        return Prestasi.objects.create(**data)

    def data_form(self, **kw):
        data = {
            'nama_prestasi': 'LKS Web', 'kategori_prestasi': 'akademik', 'subkategori': self.sub_mtk.pk,
            'penyelenggara': 'Disdik Jabar', 'wilayah_prestasi': 'dalam_negeri',
            'tingkat_prestasi': 'provinsi', 'jenis_perolehan': 'juara_2',
            'tanggal_prestasi': '2026-09-01', 'deskripsi': 'Juara 2 LKS',
            'tautan_pendukung': 'https://contoh.id/lks', 'pernyataan': 'on',
        }
        data.update(kw)
        return data

    def sebagai_kesiswaan(self):
        c = Client()
        masuk(c, self.kes.user)
        return c

    def sebagai_siswa(self, siswa=None):
        c = Client()
        masuk(c, (siswa or self.siswa).users)
        return c


# ───────────────────────── Form ─────────────────────────
class FormPengajuanTes(DasarTes):
    def test_valid_dengan_tautan_saja(self):
        form = PrestasiUploadForm(self.data_form())
        self.assertTrue(form.is_valid(), form.errors)

    def test_tanpa_bukti_apa_pun_ditolak(self):
        form = PrestasiUploadForm(self.data_form(tautan_pendukung=''))
        self.assertFalse(form.is_valid())
        self.assertIn('minimal satu bukti', ' '.join(form.non_field_errors()))

    def test_pernyataan_wajib(self):
        data = self.data_form()
        data.pop('pernyataan')
        self.assertFalse(PrestasiUploadForm(data).is_valid())

    def test_tanggal_masa_depan_ditolak(self):
        besok = (timezone.localdate() + datetime.timedelta(days=1)).isoformat()
        form = PrestasiUploadForm(self.data_form(tanggal_prestasi=besok))
        self.assertIn('tanggal_prestasi', form.errors)

    def test_tanggal_mulai_setelah_selesai_ditolak(self):
        form = PrestasiUploadForm(self.data_form(tanggal_mulai='2026-09-05'))
        self.assertIn('tanggal_mulai', form.errors)

    def test_luar_negeri_tidak_boleh_tingkat_sekolah(self):
        form = PrestasiUploadForm(self.data_form(wilayah_prestasi='luar_negeri', tingkat_prestasi='sekolah'))
        self.assertIn('tingkat_prestasi', form.errors)
        ok = PrestasiUploadForm(self.data_form(wilayah_prestasi='luar_negeri', tingkat_prestasi='regional'))
        self.assertTrue(ok.is_valid(), ok.errors)

    def test_subkategori_harus_sesuai_kategori(self):
        form = PrestasiUploadForm(self.data_form(kategori_prestasi='akademik', subkategori=self.sub_futsal.pk))
        self.assertIn('subkategori', form.errors)

    def test_lainnya_wajib_diketik_dan_nonlainnya_dikosongkan(self):
        form = PrestasiUploadForm(self.data_form(subkategori=self.sub_lain_akad.pk))
        self.assertIn('subkategori_lainnya', form.errors)
        ok = PrestasiUploadForm(self.data_form(subkategori=self.sub_lain_akad.pk, subkategori_lainnya='  Catur  '))
        self.assertTrue(ok.is_valid(), ok.errors)
        self.assertEqual(ok.cleaned_data['subkategori_lainnya'], 'Catur')
        abaikan = PrestasiUploadForm(self.data_form(subkategori_lainnya='sisa teks'))
        self.assertTrue(abaikan.is_valid())
        self.assertEqual(abaikan.cleaned_data['subkategori_lainnya'], '')

    def test_subkategori_nonaktif_tidak_bisa_dipilih(self):
        self.sub_mtk.aktif = False
        self.sub_mtk.save()
        self.assertIn('subkategori', PrestasiUploadForm(self.data_form()).errors)

    def test_tautan_harus_url(self):
        self.assertIn('tautan_pendukung', PrestasiUploadForm(self.data_form(tautan_pendukung='bukan url')).errors)

    def test_form_edit_memakai_aturan_yang_sama(self):
        data = self.data_form()
        data.pop('pernyataan')
        self.assertTrue(PrestasiEditForm(data).is_valid())
        self.assertFalse(PrestasiEditForm(self.data_form(jenis_perolehan='')).is_valid())

    def test_tingkat_regional_tersedia(self):
        pilihan = dict(PrestasiUploadForm().fields['tingkat_prestasi'].choices)
        self.assertEqual(pilihan['regional'], 'Regional/Asia')
        self.assertIn('sekolah', pilihan)


# ───────────────────────── Pengajuan siswa (view) ─────────────────────────
class PengajuanSiswaTes(DasarTes):
    def test_pengajuan_dengan_tautan_membuat_prestasi_pending_dan_riwayat(self):
        c = self.sebagai_siswa()
        r = c.post(reverse('siswa_upload_prestasi'), self.data_form())
        self.assertEqual(r.status_code, 302, getattr(r, 'context', None) and r.context['form'].errors)
        p = Prestasi.objects.get()
        self.assertEqual(p.status, 'pending')
        self.assertEqual(p.siswa, self.siswa)
        self.assertEqual(p.kategori_prestasi, 'akademik')
        self.assertEqual(p.jenis_perolehan, 'juara_2')
        self.assertEqual(Sertifikat.objects.count(), 0)
        riwayat = p.riwayat_verifikasi.get()
        self.assertEqual((riwayat.aksi, riwayat.role_pelaku, riwayat.status_baru), ('diajukan', 'siswa', 'pending'))

    def test_pengajuan_tanpa_bukti_tidak_tersimpan(self):
        c = self.sebagai_siswa()
        r = c.post(reverse('siswa_upload_prestasi'), self.data_form(tautan_pendukung=''))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Prestasi.objects.count(), 0)

    def test_halaman_form_memuat_data_dependen_dan_layout_form_user(self):
        r = self.sebagai_siswa().get(reverse('siswa_upload_prestasi'))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'data-subkategori')
        self.assertContains(r, 'Regional/Asia')
        self.assertContains(r, 'form-layout')           # memakai grid form milik design.css user
        self.assertContains(r, 'form-actions')

    def test_siswa_tidak_bisa_lihat_prestasi_siswa_lain(self):
        lain = buat_siswa(nis='2002', nama='Cici')
        p = self.buat_prestasi()
        r = self.sebagai_siswa(lain).get(reverse('siswa_prestasi_detail', args=[p.id]))
        self.assertEqual(r.status_code, 404)

    def test_detail_siswa_menampilkan_riwayat_dan_klasifikasi(self):
        p = self.buat_prestasi()
        prestasi_utils.catat_riwayat(p, 'diajukan', 'Budi', 'siswa', '', 'pending', 'Pengajuan')
        r = self.sebagai_siswa().get(reverse('siswa_prestasi_detail', args=[p.id]))
        self.assertContains(r, 'Riwayat Verifikasi')
        self.assertContains(r, 'Matematika')
        self.assertContains(r, 'Juara 1')

    def test_tidak_ada_fitur_bobot(self):
        self.assertFalse(hasattr(Prestasi, 'bobot'))
        r = self.sebagai_siswa().get(reverse('siswa_upload_prestasi'))
        self.assertNotContains(r, 'bobot')


# ───────────────────────── Verifikasi kesiswaan ─────────────────────────
class VerifikasiTes(DasarTes):
    def test_terima_mencatat_riwayat_dan_notifikasi(self):
        p = self.buat_prestasi()
        r = self.sebagai_kesiswaan().post(reverse('kesiswaan_verifikasi_detail', args=[p.id]), {'keputusan': 'diterima'})
        self.assertEqual(r.status_code, 302)
        p.refresh_from_db()
        self.assertEqual(p.status, 'diterima')
        self.assertEqual(p.kesiswaan, self.kes)
        riw = p.riwayat_verifikasi.get()
        self.assertEqual((riw.aksi, riw.status_sebelum, riw.status_baru, riw.pelaku), ('diterima', 'pending', 'diterima', 'Pak Kes'))
        self.assertTrue(NotifikasiSiswa.objects.filter(prestasi=p, status='diterima').exists())

    def test_perbaikan_data_wajib_catatan_dan_dicatat(self):
        p = self.buat_prestasi()
        url = reverse('kesiswaan_verifikasi_detail', args=[p.id])
        c = self.sebagai_kesiswaan()
        c.post(url, {'keputusan': 'perbaikan', 'jenis_perbaikan': 'data', 'catatan_perbaikan': ''})
        p.refresh_from_db(); self.assertEqual(p.status, 'pending')
        c.post(url, {'keputusan': 'perbaikan', 'jenis_perbaikan': 'data', 'catatan_perbaikan': 'Tanggal salah'})
        p.refresh_from_db()
        self.assertEqual((p.status, p.jenis_perbaikan), ('perbaikan', 'data'))
        self.assertIn('Tanggal salah', p.riwayat_verifikasi.get().catatan)

    def test_tolak_wajib_alasan_dan_menghapus_file(self):
        p = self.buat_prestasi()
        url = reverse('kesiswaan_verifikasi_detail', args=[p.id])
        c = self.sebagai_kesiswaan()
        with mock.patch('eprestasi.kesiswaan_views.hapus_semua_file_prestasi') as hapus:
            c.post(url, {'keputusan': 'ditolak', 'alasan_penolakan': ''})
            hapus.assert_not_called()
            c.post(url, {'keputusan': 'ditolak', 'alasan_penolakan': 'Bukti palsu'})
            hapus.assert_called_once()
        p.refresh_from_db()
        self.assertEqual((p.status, p.alasan_penolakan), ('ditolak', 'Bukti palsu'))
        self.assertEqual(p.riwayat_verifikasi.get().aksi, 'ditolak')

    def test_keputusan_tidak_bisa_diubah_setelah_final(self):
        p = self.buat_prestasi(status='ditolak')
        r = self.sebagai_kesiswaan().post(reverse('kesiswaan_verifikasi_detail', args=[p.id]), {'keputusan': 'diterima'})
        self.assertEqual(r.status_code, 302)
        p.refresh_from_db()
        self.assertEqual(p.status, 'ditolak')
        self.assertEqual(p.riwayat_verifikasi.count(), 0)

    def test_alur_perbaikan_data_sampai_diajukan_ulang(self):
        p = self.buat_prestasi()
        self.sebagai_kesiswaan().post(reverse('kesiswaan_verifikasi_detail', args=[p.id]),
                                      {'keputusan': 'perbaikan', 'jenis_perbaikan': 'data', 'catatan_perbaikan': 'Perbaiki tingkat'})
        data = self.data_form(nama_prestasi='Olimpiade Matematika', tingkat_prestasi='nasional', jenis_perolehan='juara_1')
        data.pop('pernyataan')
        r = self.sebagai_siswa().post(reverse('siswa_edit_prestasi_data', args=[p.id]), data)
        self.assertEqual(r.status_code, 302, getattr(r, 'context', None) and r.context['form'].errors)
        p.refresh_from_db()
        self.assertEqual(p.status, 'pending')
        self.assertEqual([x.aksi for x in p.riwayat_verifikasi.all()], ['perbaikan', 'diajukan_ulang'])

    def test_halaman_edit_perbaikan_memakai_layout_user(self):
        p = self.buat_prestasi(status='perbaikan', jenis_perbaikan='data', catatan_perbaikan='cek')
        r = self.sebagai_siswa().get(reverse('siswa_edit_prestasi_data', args=[p.id]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'form-layout')

    def test_peringatan_duplikat_tidak_menghapus(self):
        a = self.buat_prestasi(nomor_sertifikat='123/A')
        b = self.buat_prestasi(nomor_sertifikat='999/Z')
        r = self.buat_prestasi(nama_prestasi='Lain', nomor_sertifikat='123/a', tanggal_prestasi=datetime.date(2026, 1, 1))
        self.assertEqual(set(prestasi_utils.cari_duplikat(a)), {b, r})
        resp = self.sebagai_kesiswaan().get(reverse('kesiswaan_verifikasi_detail', args=[a.id]))
        self.assertContains(resp, 'Kemungkinan duplikat')
        self.assertEqual(Prestasi.objects.count(), 3)

    def test_ditolak_tidak_dihitung_duplikat(self):
        a = self.buat_prestasi()
        self.buat_prestasi(status='ditolak')
        self.assertEqual(prestasi_utils.cari_duplikat(a).count(), 0)

    def test_lengkapi_data_prestasi_lama_dicatat(self):
        lama = self.buat_prestasi(status='diterima', jenis_perolehan='', subkategori=None, tautan_pendukung='')
        r = self.sebagai_kesiswaan().post(reverse('kesiswaan_lengkapi_data', args=[lama.id]),
                                          {'jenis_perolehan': 'juara_3', 'subkategori': self.sub_mtk.pk, 'nomor_sertifikat': 'NO-1'})
        self.assertEqual(r.status_code, 302)
        lama.refresh_from_db()
        self.assertEqual((lama.jenis_perolehan, lama.nomor_sertifikat, lama.subkategori), ('juara_3', 'NO-1', self.sub_mtk))
        riw = lama.riwayat_verifikasi.get()
        self.assertEqual(riw.aksi, 'data_dilengkapi')
        self.assertIn('Juara 3', riw.catatan)
        self.assertEqual(lama.status, 'diterima')

    def test_lengkapi_data_ditolak_untuk_prestasi_ditolak_dan_subkategori_salah_kategori(self):
        ditolak = self.buat_prestasi(status='ditolak')
        c = self.sebagai_kesiswaan()
        c.post(reverse('kesiswaan_lengkapi_data', args=[ditolak.id]), {'jenis_perolehan': 'juara_3'})
        ditolak.refresh_from_db(); self.assertEqual(ditolak.jenis_perolehan, 'juara_1')
        p = self.buat_prestasi(nama_prestasi='Lain')
        c.post(reverse('kesiswaan_lengkapi_data', args=[p.id]), {'subkategori': self.sub_futsal.pk})
        p.refresh_from_db(); self.assertEqual(p.subkategori, self.sub_mtk)

    def test_riwayat_bersifat_append_only(self):
        p = self.buat_prestasi()
        self.sebagai_kesiswaan().post(reverse('kesiswaan_verifikasi_detail', args=[p.id]), {'keputusan': 'diterima'})
        sebelum = p.riwayat_verifikasi.count()
        self.sebagai_kesiswaan().post(reverse('kesiswaan_lengkapi_data', args=[p.id]), {'jenis_perolehan': 'juara_2'})
        self.assertEqual(p.riwayat_verifikasi.count(), sebelum + 1)


# ───────────────────────── Hak akses ─────────────────────────
class HakAksesTes(DasarTes):
    def test_siswa_tidak_boleh_ke_halaman_kesiswaan_dan_admin(self):
        p = self.buat_prestasi()
        c = self.sebagai_siswa()
        for nama, args in [('kesiswaan_verifikasi_detail', [p.id]), ('kesiswaan_lengkapi_data', [p.id]),
                           ('kesiswaan_export_excel', []), ('kesiswaan_cetak_rekap', []),
                           ('kesiswaan_data_prestasi', []), ('master_prestasi', [])]:
            r = c.get(reverse(nama, args=args))
            self.assertEqual(r.status_code, 302, nama)
        c.post(reverse('kesiswaan_verifikasi_detail', args=[p.id]), {'keputusan': 'diterima'})
        p.refresh_from_db()
        self.assertEqual(p.status, 'pending')

    def test_kesiswaan_tidak_boleh_mengubah_master_kategori(self):
        c = self.sebagai_kesiswaan()
        r = c.post(reverse('master_prestasi'), {'aksi': 'tambah_kategori', 'nama': 'Baru'})
        self.assertEqual(r.status_code, 302)
        self.assertFalse(KategoriPrestasi.objects.filter(nama='Baru').exists())

    def test_admin_tidak_boleh_ekspor_kesiswaan(self):
        admin = Users.objects.create(username='adm0', password='x', role='admin')
        c = Client(); masuk(c, admin)
        self.assertEqual(c.get(reverse('kesiswaan_export_excel')).status_code, 302)

    def test_anonim_dialihkan_ke_login(self):
        r = Client().get(reverse('kesiswaan_export_excel'))
        self.assertEqual(r.status_code, 302)
        self.assertIn('login', r.url)


# ───────────────────────── Admin: kategori & subkategori ─────────────────────────
class AdminMasterTes(DasarTes):
    def setUp(self):
        super().setUp()
        self.admin_user = Users.objects.create(username='adm', password='x', role='admin')
        self.c = Client()
        masuk(self.c, self.admin_user)

    def test_halaman_admin_terbuka(self):
        r = self.c.get(reverse('master_prestasi'))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Olimpiade Sains')

    def test_tambah_kategori_dan_subkategori_dan_nonaktifkan(self):
        self.c.post(reverse('master_prestasi'), {'aksi': 'tambah_kategori', 'nama': 'Keagamaan'})
        kat = KategoriPrestasi.objects.get(kode='keagamaan')
        self.assertTrue(kat.subkategori.filter(adalah_lainnya=True).exists())
        self.c.post(reverse('master_prestasi'), {'aksi': 'tambah_sub', 'kategori_id': kat.pk, 'nama': 'MTQ', 'kelompok': ''})
        sub = SubkategoriPrestasi.objects.get(nama='MTQ')
        self.c.post(reverse('master_prestasi'), {'aksi': 'tambah_sub', 'kategori_id': kat.pk, 'nama': 'mtq'})
        self.assertEqual(SubkategoriPrestasi.objects.filter(kategori=kat, nama__iexact='mtq').count(), 1)
        self.assertIn('keagamaan', [k for k, _ in PrestasiUploadForm().fields['kategori_prestasi'].choices])
        self.c.post(reverse('master_prestasi'), {'aksi': 'toggle_sub', 'id': sub.pk})
        sub.refresh_from_db(); self.assertFalse(sub.aktif)
        self.assertNotIn(sub, PrestasiUploadForm().fields['subkategori'].queryset)

    def test_nonaktifkan_subkategori_tidak_menghapus_prestasi_lama(self):
        p = self.buat_prestasi()
        self.c.post(reverse('master_prestasi'), {'aksi': 'toggle_sub', 'id': self.sub_mtk.pk})
        p.refresh_from_db()
        self.assertEqual(p.subkategori, self.sub_mtk)
        self.assertEqual(self.c.get(reverse('master_prestasi')).status_code, 200)

    def test_menu_admin_memuat_kategori_prestasi(self):
        r = self.c.get(reverse('master_prestasi'))
        self.assertContains(r, 'Kategori Prestasi')


# ───────────────────────── Rekap, ekspor setelah filter/pencarian, statistik ─────────────────────────
class RekapTes(DasarTes):
    def setUp(self):
        super().setUp()
        self.p1 = self.buat_prestasi(status='diterima')
        self.p2 = self.buat_prestasi(status='diterima', nama_prestasi='Lomba Futsal', kategori_prestasi='non-akademik',
                                     subkategori=self.sub_futsal, tingkat_prestasi='provinsi', jenis_perolehan='juara_3',
                                     tautan_pendukung='')
        self.p3 = self.buat_prestasi(status='pending', nama_prestasi='Belum Selesai', jenis_perolehan='juara_1')
        self.p4 = self.buat_prestasi(status='diterima', nama_prestasi='Peserta Saja', jenis_perolehan='peserta')
        self.p5 = self.buat_prestasi(status='ditolak', nama_prestasi='Ditolak Dulu', jenis_perolehan='juara_2')

    # -- helper --
    def baris_excel(self, params):
        from openpyxl import load_workbook
        r = self.sebagai_kesiswaan().get(reverse('kesiswaan_export_excel'), params)
        self.assertEqual(r.status_code, 200)
        self.assertIn('spreadsheetml', r['Content-Type'])
        wb = load_workbook(io.BytesIO(r.content))
        return wb, sorted(row[5].value for row in wb['Leger Prestasi'].iter_rows(min_row=5) if row[5].value)

    def nama_tabel(self, nama_url, params):
        r = self.sebagai_kesiswaan().get(reverse(nama_url), params)
        self.assertEqual(r.status_code, 200)
        return r, sorted(p.nama_prestasi for p in r.context['paginator'].object_list)

    # -- tabel --
    def test_filter_subkategori_perolehan_dan_pencarian(self):
        for params, harap in [
            ({'subkategori': self.sub_futsal.pk}, ['Lomba Futsal']),
            ({'perolehan': 'peserta'}, ['Peserta Saja']),
            ({'q': 'Futsal'}, ['Lomba Futsal']),
            ({'tingkat_prestasi': 'provinsi'}, ['Lomba Futsal']),
        ]:
            _, nama = self.nama_tabel('kesiswaan_data_prestasi', {'tahun': self.ta.id, **params})
            self.assertEqual(nama, harap, params)

    def test_total_terverifikasi_mengikuti_filter(self):
        r, _ = self.nama_tabel('kesiswaan_data_prestasi', {'tahun': self.ta.id})
        self.assertEqual(r.context['total_terverifikasi'], 3)
        r, _ = self.nama_tabel('kesiswaan_data_prestasi', {'tahun': self.ta.id, 'kategori': 'non-akademik'})
        self.assertEqual(r.context['total_terverifikasi'], 1)

    def test_tidak_ada_baris_ganda(self):
        r, _ = self.nama_tabel('kesiswaan_data_prestasi', {'tahun': self.ta.id})
        ids = [p.id for p in r.context['paginator'].object_list]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(ids), 5)

    def test_tombol_ekspor_ada_di_tiga_halaman_tabel(self):
        c = self.sebagai_kesiswaan()
        for nama, halaman in [('kesiswaan_data_prestasi', 'data'), ('kesiswaan_verifikasi_list', 'verifikasi'),
                              ('kesiswaan_riwayat', 'riwayat')]:
            r = c.get(reverse(nama))
            self.assertEqual(r.status_code, 200, nama)
            self.assertContains(r, f'halaman={halaman}', msg_prefix=nama)
            self.assertContains(r, 'Excel')
            self.assertContains(r, 'Cetak / PDF')
        self.assertNotContains(c.get(reverse('kesiswaan_dashboard')), 'kesiswaan_export')   # dashboard tanpa tombol

    # -- ekspor setelah filter / pencarian --
    def test_ekspor_tanpa_filter_memuat_semua_pada_tahun(self):
        wb, nama = self.baris_excel({'halaman': 'data', 'tahun': self.ta.id})
        self.assertEqual(wb.sheetnames, ['Leger Prestasi', 'Rekap per Siswa', 'Ringkasan Tingkat'])
        self.assertEqual(nama, sorted(['Belum Selesai', 'Ditolak Dulu', 'Lomba Futsal', 'Olimpiade Matematika', 'Peserta Saja']))

    def test_ekspor_setelah_filter_hanya_baris_terfilter(self):
        _, nama = self.baris_excel({'halaman': 'data', 'tahun': self.ta.id, 'kategori': 'non-akademik'})
        self.assertEqual(nama, ['Lomba Futsal'])
        _, nama = self.baris_excel({'halaman': 'data', 'tahun': self.ta.id, 'perolehan': 'peserta'})
        self.assertEqual(nama, ['Peserta Saja'])
        _, nama = self.baris_excel({'halaman': 'data', 'tahun': self.ta.id, 'status': 'ditolak'})
        self.assertEqual(nama, ['Ditolak Dulu'])

    def test_ekspor_setelah_pencarian_hanya_hasil_cari(self):
        _, nama = self.baris_excel({'halaman': 'data', 'tahun': self.ta.id, 'q': 'Futsal'})
        self.assertEqual(nama, ['Lomba Futsal'])
        _, nama = self.baris_excel({'halaman': 'data', 'tahun': self.ta.id, 'q': 'tidak-ada-nama-ini'})
        self.assertEqual(nama, [])
        # pencarian + filter digabung
        _, nama = self.baris_excel({'halaman': 'data', 'tahun': self.ta.id, 'q': 'Olimpiade', 'tingkat_prestasi': 'nasional'})
        self.assertEqual(nama, ['Olimpiade Matematika'])

    def test_ekspor_identik_dengan_tabel_di_setiap_halaman_memakai_qs_ekspor(self):
        """Tombol ekspor memakai qs_ekspor dari halaman; hasilnya harus sama persis dengan baris tabel."""
        c = self.sebagai_kesiswaan()
        kasus = [
            ('kesiswaan_data_prestasi', 'data', {'q': 'Olimpiade'}),
            ('kesiswaan_data_prestasi', 'data', {'kategori': 'non-akademik'}),
            ('kesiswaan_verifikasi_list', 'verifikasi', {}),                       # default status = pending
            ('kesiswaan_verifikasi_list', 'verifikasi', {'status': 'diterima', 'q': 'Peserta'}),
            ('kesiswaan_riwayat', 'riwayat', {}),
            ('kesiswaan_riwayat', 'riwayat', {'status': 'ditolak'}),
            ('kesiswaan_riwayat', 'riwayat', {'q': 'Futsal'}),
        ]
        for nama_url, halaman, params in kasus:
            r = c.get(reverse(nama_url), params)
            tabel = sorted(p.nama_prestasi for p in r.context['paginator'].object_list)
            qs = r.context['qs_ekspor']
            from urllib.parse import parse_qs
            kirim = {k: v[0] for k, v in parse_qs(qs, keep_blank_values=True).items()}
            kirim['halaman'] = halaman
            _, excel = self.baris_excel(kirim)
            self.assertEqual(excel, tabel, f'{nama_url} {params}')
            cetak = c.get(reverse('kesiswaan_cetak_rekap'), kirim)
            self.assertEqual(cetak.status_code, 200)
            self.assertEqual(sorted(b['kegiatan'] for b in cetak.context['baris']), tabel, f'cetak {nama_url} {params}')

    def test_ekspor_halaman_verifikasi_default_pending_dan_riwayat_tanpa_pending(self):
        _, nama = self.baris_excel({'halaman': 'verifikasi', 'status': 'pending', 'tahun': ''})
        self.assertEqual(nama, ['Belum Selesai'])
        _, nama = self.baris_excel({'halaman': 'riwayat', 'tahun': ''})
        self.assertNotIn('Belum Selesai', nama)
        self.assertEqual(len(nama), 4)

    def test_halaman_tak_dikenal_jatuh_ke_data(self):
        _, nama = self.baris_excel({'halaman': 'ngawur', 'tahun': self.ta.id})
        self.assertEqual(len(nama), 5)

    def test_isi_excel_dan_rekap_per_siswa(self):
        wb, _ = self.baris_excel({'halaman': 'data', 'tahun': self.ta.id})
        ws = wb['Leger Prestasi']
        self.assertIn('Filter:', ws['A2'].value)
        kepala = [c.value for c in ws[4]]
        self.assertNotIn('Bobot', kepala)
        self.assertEqual(kepala[-1], 'Status')
        data = {row[5].value: [c.value for c in row] for row in ws.iter_rows(min_row=5)}
        olim = data['Olimpiade Matematika']
        self.assertEqual((olim[1], olim[2], olim[6], olim[11], olim[16 - 1]), ('Budi', '1001', 'Akademik', 'Juara 1', 'Terverifikasi'))
        self.assertEqual(data['Belum Selesai'][15], 'Menunggu verifikasi')
        rekap = [[c.value for c in row] for row in wb['Rekap per Siswa'].iter_rows(min_row=4)]
        self.assertEqual(rekap[0][5], 3)                      # 3 prestasi terverifikasi (pending & ditolak tidak ikut)

    def test_ekspor_mencegah_formula_injection(self):
        from openpyxl import load_workbook
        self.buat_prestasi(status='diterima', nama_prestasi='=HYPERLINK("http://jahat")', jenis_perolehan='juara_1')
        r = self.sebagai_kesiswaan().get(reverse('kesiswaan_export_excel'), {'tahun': self.ta.id})
        wb = load_workbook(io.BytesIO(r.content))
        kegiatan = [row[5].value for row in wb['Leger Prestasi'].iter_rows(min_row=5)]
        self.assertTrue(any(k.startswith("'=") for k in kegiatan))
        self.assertFalse(any(k.startswith('=') for k in kegiatan))

    def test_cetak_rekap(self):
        r = self.sebagai_kesiswaan().get(reverse('kesiswaan_cetak_rekap'), {'tahun': self.ta.id, 'q': 'Olimpiade'})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Leger Prestasi Siswa')
        self.assertContains(r, 'Olimpiade Matematika')
        self.assertNotContains(r, 'Lomba Futsal')
        self.assertContains(r, 'pencarian &quot;Olimpiade&quot;')
        self.assertContains(r, 'belum memuat pengesahan')
        self.assertNotContains(r, 'obot')

    # -- halaman lain --
    def test_statistik_menampilkan_perolehan(self):
        r = self.sebagai_kesiswaan().get(reverse('kesiswaan_statistik'), {'tahun': self.ta.id})
        self.assertEqual(r.status_code, 200)
        data = r.context['chart_data']['perolehan']
        self.assertEqual(dict(zip(data['labels'], data['data'])), {'Juara 1': 1, 'Juara 3': 1, 'Peserta': 1})
        self.assertNotContains(r, 'Total Bobot')

    def test_halaman_kesiswaan_lain_tetap_berjalan(self):
        c = self.sebagai_kesiswaan()
        for nama in ('kesiswaan_dashboard', 'kesiswaan_verifikasi_list', 'kesiswaan_riwayat'):
            self.assertEqual(c.get(reverse(nama)).status_code, 200, nama)
        for p in (self.p1, self.p3, self.p5):
            self.assertEqual(c.get(reverse('kesiswaan_verifikasi_detail', args=[p.id])).status_code, 200)

    def test_halaman_siswa_lain_tetap_berjalan(self):
        c = self.sebagai_siswa()
        for nama in ('siswa_dashboard', 'siswa_prestasi_list', 'siswa_panduan'):
            self.assertEqual(c.get(reverse(nama)).status_code, 200, nama)
