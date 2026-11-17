"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.conf import settings
from django.contrib import admin
from django.urls import path, include
from django.urls import path
from eprestasi import views
from eprestasi import auth_views
from eprestasi import admin_views
from eprestasi import siswa_views
from eprestasi import kesiswaan_views

urlpatterns = [
    # Autentikasi
    path('',views.landing_page, name='landing_page'),
    path('api/cari-siswa/', views.cari_siswa_api, name='cari_siswa_api'),
    path('login/', auth_views.login_view, name='login'),
    path('logout/', auth_views.logout_view, name='logout'),

    # Lupa password (siswa)
    path('lupa-password/', siswa_views.lupa_password, name='lupa_password'),
    path('lupa-password/metode/', siswa_views.lupa_password_metode, name='lupa_password_metode'),
    path('lupa-password/verifikasi/', siswa_views.lupa_password_verifikasi, name='lupa_password_verifikasi'),
    path('lupa-password/baru/', siswa_views.lupa_password_baru, name='lupa_password_baru'),

    # Permintaan reset password (admin)
    path('permintaan-reset-password/', admin_views.permintaan_reset_list, name='permintaan_reset_list'),
    path('permintaan-reset-password/<int:permintaan_id>/proses/', admin_views.permintaan_reset_proses, name='permintaan_reset_proses'),
    path('permintaan-reset-password/<int:permintaan_id>/tolak/', admin_views.permintaan_reset_tolak, name='permintaan_reset_tolak'),

    # Portal Siswa
    path('siswa/dashboard/', siswa_views.dashboard, name='siswa_dashboard'),
    path('siswa/profil/', siswa_views.lengkapi_profil, name='siswa_lengkapi_profil'),

    # Prestasi milik siswa (portal siswa)
    path('siswa/prestasi/', siswa_views.prestasi_list, name='siswa_prestasi_list'),
    path('siswa/prestasi/upload/', siswa_views.upload_prestasi, name='siswa_upload_prestasi'),
    path('siswa/prestasi/<int:prestasi_id>/', siswa_views.prestasi_detail, name='siswa_prestasi_detail'),
    path('siswa/prestasi/<int:prestasi_id>/tambah-sertifikat/', siswa_views.tambah_sertifikat, name='siswa_tambah_sertifikat'),
    path('siswa/prestasi/<int:prestasi_id>/edit-data/', siswa_views.edit_prestasi_data, name='siswa_edit_prestasi_data'),
    path('siswa/prestasi/<int:prestasi_id>/tambah-dokumentasi/', siswa_views.tambah_dokumentasi, name='siswa_tambah_dokumentasi'),
    path('siswa/prestasi/<int:prestasi_id>/hapus/', siswa_views.hapus_prestasi, name='siswa_hapus_prestasi'),

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
    path('admin/dashboard/', admin_views.dashboard, name='dashboard'),

    # Siswa
    path('siswa/', admin_views.siswa_list, name='siswa_list'),
    path('siswa/tambah/', admin_views.Create_siswa, name='tambah_siswa'),
    path('siswa/edit/<int:siswa_id>/', admin_views.Update_siswa, name='update_siswa'),
    path('siswa/hapus/<int:siswa_id>/', admin_views.delete_siswa, name='delete_siswa'),
    path('siswa/keluarkan/<int:siswa_id>/', admin_views.keluarkan_siswa, name='keluarkan_siswa'),
    path('siswa/pulihkan/<int:siswa_id>/', admin_views.pulihkan_siswa, name='pulihkan_siswa'),

    # Import Excel siswa
    path('siswa/import/', admin_views.import_siswa, name='siswa_import'),
    path('siswa/import/template/', admin_views.download_template_siswa, name='siswa_import_template'),
    path('siswa/import/hasil/', admin_views.hasil_import_siswa, name='siswa_import_hasil'),
    path('siswa/import/hasil/download/', admin_views.download_hasil_import, name='siswa_import_download'),

    # Hapus massal (checkbox di daftar)
    path('siswa/hapus-massal/', admin_views.hapus_massal_siswa, name='hapus_massal_siswa'),
    path('kesiswaan/hapus-massal/', admin_views.hapus_massal_kesiswaan, name='hapus_massal_kesiswaan'),

    # Kesiswaan
    path('kesiswaan/', admin_views.kesiswaan_list, name='kesiswaan_list'),
    path('kesiswaan/tambah/', admin_views.Create_kesiswaan, name='tambah_kesiswaan'),
    path('kesiswaan/edit/<int:kesiswaan_id>/', admin_views.Update_kesiswaan, name='update_kesiswaan'),
    path('kesiswaan/hapus/<int:kesiswaan_id>/', admin_views.delete_kesiswaan, name='delete_kesiswaan'),

    # Tahun Ajaran
    path('tahun-ajaran/', admin_views.tahun_ajaran_list, name='tahun_ajaran_list'),
    path('tahun-ajaran/<int:tahun_ajaran_id>/statistik/', admin_views.tahun_ajaran_statistik, name='tahun_ajaran_statistik'),
    path('tahun-ajaran/<int:tahun_id>/kelas/', admin_views.tahun_ajaran_kelas, name='tahun_ajaran_kelas'),
    path('tahun-ajaran/<int:tahun_id>/kelas/<int:kelas_id>/siswa/', admin_views.tahun_ajaran_kelas_siswa, name='tahun_ajaran_kelas_siswa'),
    path('tahun-ajaran/tambah/', admin_views.Create_tahun_ajaran, name='tambah_tahun_ajaran'),
    path('tahun-ajaran/edit/<int:tahun_ajaran_id>/', admin_views.Update_tahun_ajaran, name='update_tahun_ajaran'),
    path('tahun-ajaran/aktifkan/<int:tahun_ajaran_id>/', admin_views.aktifkan_tahun_ajaran, name='aktifkan_tahun_ajaran'),
    path('tahun-ajaran/nonaktifkan/<int:tahun_ajaran_id>/', admin_views.nonaktifkan_tahun_ajaran, name='nonaktifkan_tahun_ajaran'),
    path('tahun-ajaran/hapus/<int:tahun_ajaran_id>/', admin_views.delete_tahun_ajaran, name='delete_tahun_ajaran'),

    # Pengelolaan Kelas & Riwayat Kelas Siswa
    path('pengelolaan-kelas/', admin_views.pengelolaan_kelas, name='pengelolaan_kelas'),
    path('pengelolaan-kelas/tempatkan/', admin_views.tempatkan_siswa, name='tempatkan_siswa'),
    path('pengelolaan-kelas/cek-nis/', admin_views.cek_nis_massal, name='cek_nis_massal'),
    path('pengelolaan-kelas/naikkan-otomatis/', admin_views.naikkan_otomatis, name='naikkan_otomatis'),
    path('pengelolaan-kelas/kelas/', admin_views.kelola_kelas, name='kelola_kelas'),
    path('pengelolaan-kelas/kelas/tambah/', admin_views.tambah_kelas, name='tambah_kelas'),
    path('pengelolaan-kelas/kelas/buat-massal/', admin_views.buat_kelas_massal, name='buat_kelas_massal'),
    path('pengelolaan-kelas/kelas/salin/', admin_views.salin_kelas, name='salin_kelas'),
    path('pengelolaan-kelas/kelas/hapus/<int:kelas_id>/', admin_views.hapus_kelas, name='hapus_kelas'),
    path('pengelolaan-kelas/riwayat-kelas/', admin_views.riwayat_berdasarkan_kelas, name='riwayat_berdasarkan_kelas'),
    path('pengelolaan-kelas/log-perubahan/', admin_views.log_perubahan_kelas, name='log_perubahan_kelas'),
    path('siswa/<int:siswa_id>/riwayat-kelas/', admin_views.riwayat_kelas_siswa, name='riwayat_kelas_siswa'),

    # Kelulusan & Alumni
    path('kelulusan-alumni/', admin_views.kelulusan_alumni, name='kelulusan_alumni'),
    path('kelulusan-alumni/proses/', admin_views.proses_kelulusan, name='proses_kelulusan'),
    path('kelulusan-alumni/tidak-lulus/', admin_views.tandai_tidak_lulus, name='tandai_tidak_lulus'),

    # Profil Admin (admin & super_admin)
    path('profil/', admin_views.profil_admin, name='profil_admin'),

    # Kelola Admin (khusus super_admin)
    path('kelola-admin/', admin_views.admin_list, name='admin_list'),
    path('kelola-admin/tambah/', admin_views.Create_admin, name='tambah_admin'),
    path('kelola-admin/edit/<int:admin_id>/', admin_views.Update_admin, name='update_admin'),
    path('kelola-admin/hapus/<int:admin_id>/', admin_views.delete_admin, name='delete_admin'),

    # --- siswa: panduan & import Excel bertahap ---
    path('siswa/panduan/', siswa_views.panduan, name='siswa_panduan'),
    path('siswa/import/mulai/', admin_views.import_siswa_mulai, name='siswa_import_mulai'),
    path('siswa/import/proses/', admin_views.import_siswa_proses, name='siswa_import_proses'),
    path('siswa/import/batal/', admin_views.import_siswa_batal, name='siswa_import_batal'),
    path('siswa/import/status/', admin_views.import_siswa_status, name='siswa_import_status'),
    path('siswa/import/tutup/', admin_views.import_siswa_tutup, name='siswa_import_tutup'),

    # --- fitur prestasi (kesiswaan & master data) ---
    path('kesiswaan/verifikasi/<int:prestasi_id>/lengkapi/', kesiswaan_views.lengkapi_data, name='kesiswaan_lengkapi_data'),
    path('kesiswaan/rekap/excel/', kesiswaan_views.export_rekap_excel, name='kesiswaan_export_excel'),
    path('kesiswaan/rekap/cetak/', kesiswaan_views.cetak_rekap, name='kesiswaan_cetak_rekap'),
    path('master-prestasi/', admin_views.master_prestasi, name='master_prestasi'),
]