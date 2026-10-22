from django.contrib import admin
from .models import (
    Users, Siswa, Kesiswaan, Tahun_ajaran, Prestasi, Sertifikat, Dokumentasi,
    Kelas, RiwayatKelas, LogPerubahanKelas,
)


@admin.register(Users)
class UsersAdmin(admin.ModelAdmin):
    list_display = ('id', 'username', 'role', 'npsn', 'created_at')
    list_filter = ('role', 'npsn')
    search_fields = ('username',)


@admin.register(Siswa)
class SiswaAdmin(admin.ModelAdmin):
    list_display = ('id', 'nis', 'nama', 'tingkat', 'kelas', 'jurusan', 'status', 'jenis_keluar', 'tanggal_keluar')
    list_filter = ('status', 'tingkat', 'jurusan')
    search_fields = ('nama', 'nis')


@admin.register(Kesiswaan)
class KesiswaanAdmin(admin.ModelAdmin):
    list_display = ('id', 'nama', 'nip', 'jabatan')
    search_fields = ('nama', 'nip')


@admin.register(Tahun_ajaran)
class TahunAjaranAdmin(admin.ModelAdmin):
    list_display = ('id', 'tahun_ajaran', 'status')
    list_filter = ('status',)


admin.site.register(Prestasi)
admin.site.register(Dokumentasi)


@admin.register(Sertifikat)
class SertifikatAdmin(admin.ModelAdmin):
    list_select_related = ('prestasi',)   # __str__ memakai prestasi.nama_prestasi


@admin.register(Kelas)
class KelasAdmin(admin.ModelAdmin):
    list_display = ('id', 'nama_kelas', 'jurusan', 'tingkat', 'tahun_ajaran')
    list_filter = ('tahun_ajaran', 'jurusan', 'tingkat')
    search_fields = ('nama_kelas',)


class _KelasSelectRelatedMixin:
    """Dropdown Kelas memanggil Kelas.__str__ (yang membuka tahun_ajaran) untuk tiap opsi;
    select_related mencegahnya jadi 1 query per kelas."""
    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name in ('kelas', 'kelas_sebelumnya', 'kelas_baru'):
            kwargs['queryset'] = Kelas.objects.select_related('tahun_ajaran')
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


@admin.register(RiwayatKelas)
class RiwayatKelasAdmin(_KelasSelectRelatedMixin, admin.ModelAdmin):
    list_display = ('id', 'siswa', 'kelas', 'tahun_ajaran', 'tingkat', 'tanggal_penempatan')
    list_select_related = ('siswa', 'kelas__tahun_ajaran', 'tahun_ajaran')
    list_filter = ('tahun_ajaran', 'tingkat')
    search_fields = ('siswa__nama', 'siswa__nis')


@admin.register(LogPerubahanKelas)
class LogPerubahanKelasAdmin(_KelasSelectRelatedMixin, admin.ModelAdmin):
    list_display = ('id', 'siswa', 'kelas_sebelumnya', 'kelas_baru', 'tahun_ajaran', 'jenis_perubahan', 'waktu_perubahan')
    list_select_related = ('siswa', 'kelas_sebelumnya__tahun_ajaran', 'kelas_baru__tahun_ajaran', 'tahun_ajaran')
    list_filter = ('tahun_ajaran', 'jenis_perubahan')
    search_fields = ('siswa__nama', 'siswa__nis')
