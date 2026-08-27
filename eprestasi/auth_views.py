from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth.hashers import check_password

from .models import Users, Siswa, Kesiswaan


def login_view(request):
    """
    Halaman login untuk 3 role: siswa, kesiswaan, admin.
    """
    if request.session.get('user_id'):
        return _redirect_by_role(request.session.get('role'))

    role_dipilih = request.POST.get('role', request.GET.get('role', 'siswa'))
    if role_dipilih not in ('siswa', 'kesiswaan', 'admin'):
        role_dipilih = 'siswa'

    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')

        role_yang_dicari = ['admin', 'super_admin'] if role_dipilih == 'admin' else [role_dipilih]
        user = Users.objects.filter(username=username, role__in=role_yang_dicari).first()

        if user is None or not check_password(password, user.password):
            messages.error(request, 'NIS/NIP/Username atau password salah.')
            return render(request, 'eprestasi/login.html', {'role_dipilih': role_dipilih})

        # =========================================================
        # CARI NAMA LENGKAP DARI TABEL PROFIL BERDASARKAN ROLE
        # =========================================================
        nama_tampil = user.username # Default fallback jika profil belum diisi

        # CONTOH A: Jika Kamu Menggunakan 1 Tabel Profil Gabungan (misal: ProfilUser)
        # profil = ProfilUser.objects.filter(user=user).first()
        # if profil and profil.nama_lengkap:
        #     nama_tampil = profil.nama_lengkap

        # CONTOH B: Jika Tabel Profil Dipisah Berdasarkan Role
        if user.role == 'siswa':
            profil = Siswa.objects.filter(users=user).first() # Sesuaikan nama model & FK
            if profil and profil.nama:
                nama_tampil = profil.nama

        elif user.role in ('kesiswaan', 'admin', 'super_admin'):
            profil = Kesiswaan.objects.filter(user=user).first() # Sesuaikan nama model & FK
            if profil and profil.nama:
                nama_tampil = profil.nama

        # =========================================================
        # SIMPAN IDENTITAS KEPADA SESSION
        # =========================================================
        request.session['user_id'] = user.id
        request.session['username'] = user.username
        request.session['role'] = user.role
        request.session['nama'] = nama_tampil  # <--- Disimpan di sini!

        messages.success(request, f'Selamat datang, {nama_tampil}!')
        return _redirect_by_role(user.role)

    return render(request, 'eprestasi/login.html', {'role_dipilih': role_dipilih})

def logout_view(request):
    request.session.flush()  # hapus semua data session (user_id, username, role)
    messages.success(request, 'Anda telah keluar.')
    return redirect('login')


def _redirect_by_role(role):
    if role in ('admin', 'super_admin'):
        return redirect('dashboard')
    if role == 'siswa':
        return redirect('siswa_dashboard')
    if role == 'kesiswaan':
        return redirect('kesiswaan_dashboard')
    return redirect('login')
