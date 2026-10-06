from django.urls import path
from . import views
from . import auth_views
from . import siswa_views
from . import siswa_admin_views
from . import tahun_ajaran_views
from . import siswa_prestasi_views
from . import kesiswaan_views
from . import import_views
from . import kelas_views
from . import kelulusan_views

urlpatterns = [
    # Autentikasi
    path('',views.landing_page, name='landing_page'),
    path('api/cari-siswa/', views.cari_siswa_api, name='cari_siswa_api'),
    path('login/', auth_views.login_view, name='login'),
    path('logout/', auth_views.logout_view, name='logout'),

    # Portal Siswa
    path('siswa/dashboard/', siswa_views.dashboard, name='siswa_dashboard'),
    path('siswa/profil/', siswa_views.lengkapi_profil, name='siswa_lengkapi_profil'),

    # Prestasi milik siswa (portal siswa)
    path('siswa/prestasi/', siswa_prestasi_views.prestasi_list, name='siswa_prestasi_list'),
    path('siswa/prestasi/upload/', siswa_prestasi_views.upload_prestasi, name='siswa_upload_prestasi'),
    path('siswa/prestasi/<int:prestasi_id>/', siswa_prestasi_views.prestasi_detail, name='siswa_prestasi_detail'),
    path('siswa/prestasi/<int:prestasi_id>/tambah-sertifikat/', siswa_prestasi_views.tambah_sertifikat, name='siswa_tambah_sertifikat'),
    path('siswa/prestasi/<int:prestasi_id>/edit-data/', siswa_prestasi_views.edit_prestasi_data, name='siswa_edit_prestasi_data'),
    path('siswa/prestasi/<int:prestasi_id>/tambah-dokumentasi/', siswa_prestasi_views.tambah_dokumentasi, name='siswa_tambah_dokumentasi'),
    path('siswa/prestasi/<int:prestasi_id>/hapus/', siswa_prestasi_views.hapus_prestasi, name='siswa_hapus_prestasi'),

    # QR Code & Portofolio Publik
    path('siswa/qr-code/', siswa_views.qr_code_view, name='siswa_qr_code'),

    # Notifikasi siswa
    path('siswa/notifikasi/tandai-semua/', siswa_views.notif_tandai_semua, name='siswa_notif_semua'),
    path('siswa/notifikasi/<int:notif_id>/', siswa_views.notif_buka, name='siswa_notif_buka'),
    path('portofolio/<str:nis>/', siswa_views.portofolio_publik, name='portofolio_publik'),

    # Portal Kesiswaan
    path('kesiswaan/notifikasi/<int:prestasi_id>/', kesiswaan_views.notif_buka, name='kesiswaan_notif_buka'),
    path('kesiswaan/notifikasi/tandai-semua/', kesiswaan_views.notif_tandai_semua, name='kesiswaan_notif_semua'),
    path('kesiswaan/dashboard/', kesiswaan_views.dashboard, name='kesiswaan_dashboard'),
    path('kesiswaan/profil/', kesiswaan_views.lengkapi_profil, name='kesiswaan_lengkapi_profil'),
    path('kesiswaan/data-prestasi/', kesiswaan_views.data_prestasi, name='kesiswaan_data_prestasi'),
    path('kesiswaan/statistik/', kesiswaan_views.statistik, name='kesiswaan_statistik'),
    path('kesiswaan/verifikasi/', kesiswaan_views.verifikasi_list, name='kesiswaan_verifikasi_list'),
    path('kesiswaan/verifikasi/<int:prestasi_id>/', kesiswaan_views.verifikasi_detail, name='kesiswaan_verifikasi_detail'),
    path('kesiswaan/riwayat/', kesiswaan_views.riwayat_verifikasi, name='kesiswaan_riwayat'),

    # Dashboard admin
    path('admin/dashboard/', views.dashboard, name='dashboard'),

    # Siswa
    path('siswa/', siswa_admin_views.siswa_list, name='siswa_list'),
    path('siswa/tambah/', views.Create_siswa, name='tambah_siswa'),
    path('siswa/edit/<int:siswa_id>/', views.Update_siswa, name='update_siswa'),
    path('siswa/hapus/<int:siswa_id>/', views.delete_siswa, name='delete_siswa'),

    # Import Excel siswa
    path('siswa/import/', import_views.import_siswa, name='siswa_import'),
    path('siswa/import/template/', import_views.download_template_siswa, name='siswa_import_template'),
    path('siswa/import/hasil/', import_views.hasil_import_siswa, name='siswa_import_hasil'),
    path('siswa/import/hasil/download/', import_views.download_hasil_import, name='siswa_import_download'),

    # Kesiswaan
    path('kesiswaan/', views.kesiswaan_list, name='kesiswaan_list'),
    path('kesiswaan/tambah/', views.Create_kesiswaan, name='tambah_kesiswaan'),
    path('kesiswaan/edit/<int:kesiswaan_id>/', views.Update_kesiswaan, name='update_kesiswaan'),
    path('kesiswaan/hapus/<int:kesiswaan_id>/', views.delete_kesiswaan, name='delete_kesiswaan'),

    # Tahun Ajaran
    path('tahun-ajaran/', tahun_ajaran_views.tahun_ajaran_list, name='tahun_ajaran_list'),
    path('tahun-ajaran/<int:tahun_ajaran_id>/statistik/', tahun_ajaran_views.tahun_ajaran_statistik, name='tahun_ajaran_statistik'),
    path('tahun-ajaran/tambah/', views.Create_tahun_ajaran, name='tambah_tahun_ajaran'),
    path('tahun-ajaran/edit/<int:tahun_ajaran_id>/', views.Update_tahun_ajaran, name='update_tahun_ajaran'),
    path('tahun-ajaran/aktifkan/<int:tahun_ajaran_id>/', views.aktifkan_tahun_ajaran, name='aktifkan_tahun_ajaran'),
    path('tahun-ajaran/nonaktifkan/<int:tahun_ajaran_id>/', views.nonaktifkan_tahun_ajaran, name='nonaktifkan_tahun_ajaran'),
    path('tahun-ajaran/hapus/<int:tahun_ajaran_id>/', views.delete_tahun_ajaran, name='delete_tahun_ajaran'),

    # Pengelolaan Kelas & Riwayat Kelas Siswa
    path('pengelolaan-kelas/', kelas_views.pengelolaan_kelas, name='pengelolaan_kelas'),
    path('pengelolaan-kelas/tempatkan/', kelas_views.tempatkan_siswa, name='tempatkan_siswa'),
    path('pengelolaan-kelas/cek-nis/', kelas_views.cek_nis_massal, name='cek_nis_massal'),
    path('pengelolaan-kelas/naikkan-otomatis/', kelas_views.naikkan_otomatis, name='naikkan_otomatis'),
    path('pengelolaan-kelas/kelas/', kelas_views.kelola_kelas, name='kelola_kelas'),
    path('pengelolaan-kelas/kelas/tambah/', kelas_views.tambah_kelas, name='tambah_kelas'),
    path('pengelolaan-kelas/kelas/buat-massal/', kelas_views.buat_kelas_massal, name='buat_kelas_massal'),
    path('pengelolaan-kelas/kelas/salin/', kelas_views.salin_kelas, name='salin_kelas'),
    path('pengelolaan-kelas/kelas/hapus/<int:kelas_id>/', kelas_views.hapus_kelas, name='hapus_kelas'),
    path('pengelolaan-kelas/riwayat-kelas/', kelas_views.riwayat_berdasarkan_kelas, name='riwayat_berdasarkan_kelas'),
    path('pengelolaan-kelas/log-perubahan/', kelas_views.log_perubahan_kelas, name='log_perubahan_kelas'),
    path('siswa/<int:siswa_id>/riwayat-kelas/', kelas_views.riwayat_kelas_siswa, name='riwayat_kelas_siswa'),

    # Kelulusan & Alumni
    path('kelulusan-alumni/', kelulusan_views.kelulusan_alumni, name='kelulusan_alumni'),
    path('kelulusan-alumni/proses/', kelulusan_views.proses_kelulusan, name='proses_kelulusan'),
    path('kelulusan-alumni/tidak-lulus/', kelulusan_views.tandai_tidak_lulus, name='tandai_tidak_lulus'),

    # Profil Admin (admin & super_admin)
    path('profil/', views.profil_admin, name='profil_admin'),

    # Kelola Admin (khusus super_admin)
    path('kelola-admin/', views.admin_list, name='admin_list'),
    path('kelola-admin/tambah/', views.Create_admin, name='tambah_admin'),
    path('kelola-admin/edit/<int:admin_id>/', views.Update_admin, name='update_admin'),
    path('kelola-admin/hapus/<int:admin_id>/', views.delete_admin, name='delete_admin'),
]