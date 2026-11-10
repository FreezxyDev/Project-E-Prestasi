"""
Data awal (konfigurasi), BUKAN data prestasi: kategori & subkategori sesuai daftar sekolah.
Semuanya bisa diubah admin kapan saja lewat menu "Kategori Prestasi".
Idempotent: aman dijalankan ulang, tidak menimpa data yang sudah ada.
"""
from django.db import migrations

KATEGORI = [
    # (kode, nama, urutan) -- kode sama dengan nilai lama Prestasi.kategori_prestasi
    ('akademik', 'Akademik', 1),
    ('non-akademik', 'Non-Akademik', 2),
]

# (kode_kategori, kelompok, [nama subkategori])
SUBKATEGORI = [
    ('akademik', 'Olimpiade Sains', ['Matematika', 'Fisika', 'Kimia', 'Biologi', 'Informatika', 'Ekonomi', 'Geografi', 'Astronomi']),
    ('akademik', '', ['Lomba Cerdas Cermat', 'Karya Tulis Ilmiah', 'Debat', 'Public Speaking', 'Publikasi Ilmiah', 'Robotik dan Inovasi']),
    ('non-akademik', 'Olahraga', ['Futsal', 'Basket', 'Voli', 'Badminton', 'Renang', 'Taekwondo', 'Karate', 'Atletik', 'Panjat Tebing', 'Dayung', 'Sepeda']),
    ('non-akademik', 'Seni dan Budaya', ['Musik', 'Vokal', 'Tari', 'Lukis', 'Desain', 'Fotografi', 'Teater', 'Film/Video', 'Kaligrafi']),
    ('non-akademik', 'Kepemimpinan dan Organisasi', ['Ketua OSIS', 'Pengurus Ekstrakurikuler', 'Pramuka', 'Organisasi Lainnya']),
    ('non-akademik', 'Kepramukaan', ['Jambore', 'LKBB', 'Kirab', 'Kegiatan Kepramukaan Lainnya']),
    ('non-akademik', 'Teknologi dan Inovasi', ['Coding', 'AI', 'Robotik', 'Startup', 'Kompetisi Teknologi Lainnya']),
    ('non-akademik', 'Sosial dan Lingkungan', ['Bakti Sosial', 'Pengabdian Masyarakat', 'Kegiatan Lingkungan']),
    ('non-akademik', 'Kewirausahaan', ['Kompetisi Bisnis', 'Startup Bisnis', 'Inovasi UMKM']),
]


def isi_data_awal(apps, schema_editor):
    Kategori = apps.get_model('eprestasi', 'KategoriPrestasi')
    Sub = apps.get_model('eprestasi', 'SubkategoriPrestasi')

    kat = {}
    for kode, nama, urutan in KATEGORI:
        obj, _ = Kategori.objects.get_or_create(kode=kode, defaults={'nama': nama, 'urutan': urutan})
        kat[kode] = obj

    for kode, kelompok, daftar in SUBKATEGORI:
        for i, nama in enumerate(daftar, start=1):
            Sub.objects.get_or_create(
                kategori=kat[kode], kelompok=kelompok, nama=nama, defaults={'urutan': i},
            )
    for kode in kat:
        Sub.objects.get_or_create(
            kategori=kat[kode], kelompok='', nama='Lainnya',
            defaults={'adalah_lainnya': True, 'urutan': 999},
        )


def batal(apps, schema_editor):
    # Tidak menghapus apa pun: data master mungkin sudah dipakai prestasi.
    pass


class Migration(migrations.Migration):
    dependencies = [('eprestasi', '0031_kategori_perolehan_riwayat')]
    operations = [migrations.RunPython(isi_data_awal, batal)]
