from django.urls import path
from . import views
from . import auth_views
from . import siswa_views
from . import siswa_prestasi_views
from . import kesiswaan_views

urlpatterns = [
    # Autentikasi
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
    path('siswa/prestasi/<int:prestasi_id>/tambah-dokumentasi/', siswa_prestasi_views.tambah_dokumentasi, name='siswa_tambah_dokumentasi'),
    path('siswa/prestasi/<int:prestasi_id>/hapus/', siswa_prestasi_views.hapus_prestasi, name='siswa_hapus_prestasi'),

    # Portal Kesiswaan
    path('kesiswaan/dashboard/', kesiswaan_views.dashboard, name='kesiswaan_dashboard'),
    path('kesiswaan/profil/', kesiswaan_views.lengkapi_profil, name='kesiswaan_lengkapi_profil'),
    path('kesiswaan/verifikasi/', kesiswaan_views.verifikasi_list, name='kesiswaan_verifikasi_list'),
    path('kesiswaan/verifikasi/<int:prestasi_id>/', kesiswaan_views.verifikasi_detail, name='kesiswaan_verifikasi_detail'),
    path('kesiswaan/riwayat/', kesiswaan_views.riwayat_verifikasi, name='kesiswaan_riwayat'),

    # Dashboard admin
    path('', views.dashboard, name='dashboard'),

    # Siswa
    path('siswa/', views.siswa_list, name='siswa_list'),
    path('siswa/tambah/', views.Create_siswa, name='tambah_siswa'),
    path('siswa/edit/<int:siswa_id>/', views.Update_siswa, name='update_siswa'),
    path('siswa/hapus/<int:siswa_id>/', views.delete_siswa, name='delete_siswa'),

    # Kesiswaan
    path('kesiswaan/', views.kesiswaan_list, name='kesiswaan_list'),
    path('kesiswaan/tambah/', views.Create_kesiswaan, name='tambah_kesiswaan'),
    path('kesiswaan/edit/<int:kesiswaan_id>/', views.Update_kesiswaan, name='update_kesiswaan'),
    path('kesiswaan/hapus/<int:kesiswaan_id>/', views.delete_kesiswaan, name='delete_kesiswaan'),

    # Tahun Ajaran
    path('tahun-ajaran/', views.tahun_ajaran_list, name='tahun_ajaran_list'),
    path('tahun-ajaran/tambah/', views.Create_tahun_ajaran, name='tambah_tahun_ajaran'),
    path('tahun-ajaran/edit/<int:tahun_ajaran_id>/', views.Update_tahun_ajaran, name='update_tahun_ajaran'),
    path('tahun-ajaran/aktifkan/<int:tahun_ajaran_id>/', views.aktifkan_tahun_ajaran, name='aktifkan_tahun_ajaran'),
    path('tahun-ajaran/nonaktifkan/<int:tahun_ajaran_id>/', views.nonaktifkan_tahun_ajaran, name='nonaktifkan_tahun_ajaran'),
    path('tahun-ajaran/hapus/<int:tahun_ajaran_id>/', views.delete_tahun_ajaran, name='delete_tahun_ajaran'),

    # Kelola Admin (khusus super_admin)
    path('kelola-admin/', views.admin_list, name='admin_list'),
    path('kelola-admin/tambah/', views.Create_admin, name='tambah_admin'),
    path('kelola-admin/edit/<int:admin_id>/', views.Update_admin, name='update_admin'),
    path('kelola-admin/hapus/<int:admin_id>/', views.delete_admin, name='delete_admin'),
]
