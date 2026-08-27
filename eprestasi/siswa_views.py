from django.shortcuts import render, redirect
from django.contrib import messages

from .models import Siswa, Tahun_ajaran
from .forms import SiswaProfilForm
from .decorators import role_required


def _get_siswa(request):
    """Ambil data Siswa milik user yang sedang login (dari session)."""
    return Siswa.objects.filter(users_id=request.session.get('user_id')).first()


@role_required('siswa')
def dashboard(request):
    siswa = _get_siswa(request)
    if siswa is None:
        # Kasus langka: akun Users ber-role siswa tapi baris Siswa-nya hilang/rusak.
        messages.error(request, 'Data siswa tidak ditemukan. Hubungi admin.')
        return redirect('logout')

    # GATE UTAMA: profil belum lengkap -> paksa isi profil dulu, tidak boleh
    # lihat dashboard/upload apa pun sebelum ini terpenuhi.
    if not siswa.profil_lengkap:
        return redirect('siswa_lengkapi_profil')

    context = {
        'siswa': siswa,
        'active_menu': 'dashboard',
        'tahun_ajaran_aktif': Tahun_ajaran.objects.filter(status='aktif').first(),
    }
    return render(request, 'eprestasi/siswa_portal/dashboard.html', context)


@role_required('siswa')
def lengkapi_profil(request):
    siswa = _get_siswa(request)
    if siswa is None:
        messages.error(request, 'Data siswa tidak ditemukan. Hubungi admin.')
        return redirect('logout')

    if request.method == 'POST':
        form = SiswaProfilForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            siswa.nama = data['nama']
            siswa.kelas = data['kelas']
            siswa.jurusan = data['jurusan']
            siswa.email = data.get('email') or None
            siswa.no_hp = data.get('no_hp') or None
            siswa.save()
            messages.success(request, 'Profil berhasil disimpan.')
            return redirect('siswa_dashboard')
    else:
        # Mode edit (profil sudah lengkap, siswa buka halaman ini lagi buat koreksi)
        # -> form diisi otomatis dari data yang sudah ada.
        form = SiswaProfilForm(initial={
            'nama': siswa.nama,
            'kelas': siswa.kelas,
            'jurusan': siswa.jurusan,
            'email': siswa.email,
            'no_hp': siswa.no_hp,
        })

    context = {
        'form': form,
        'siswa': siswa,
        'active_menu': 'profil',
        # Dipakai template buat nentuin boleh/tidaknya tombol "Batal" muncul --
        # kalau profil BELUM pernah lengkap, tidak ada "dashboard" buat dibatalkan ke sana.
        'wajib_diisi': not siswa.profil_lengkap,
    }
    return render(request, 'eprestasi/siswa_portal/lengkapi_profil.html', context)
