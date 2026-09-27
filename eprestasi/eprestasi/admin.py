from django.contrib import admin
from .models import Users, Siswa, Kesiswaan, Tahun_ajaran, Prestasi, Sertifikat, Dokumentasi


@admin.register(Users)
class UsersAdmin(admin.ModelAdmin):
    list_display = ('id', 'username', 'role', 'created_at')
    list_filter = ('role',)
    search_fields = ('username',)


@admin.register(Siswa)
class SiswaAdmin(admin.ModelAdmin):
    list_display = ('id', 'nis', 'nama', 'tingkat', 'kelas', 'jurusan', 'status')
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
admin.site.register(Sertifikat)
admin.site.register(Dokumentasi)
