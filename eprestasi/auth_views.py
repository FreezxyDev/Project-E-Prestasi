from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth.hashers import check_password

from .models import Users, Siswa, Kesiswaan


def login_view(request):
    """
    Halaman login otomatis (1 field): Otomatis mendeteksi role (siswa, kesiswaan, admin).
    """
    # 1. Jika user sudah login, langsung lempar ke dashboard masing-masing
    if request.session.get('user_id'):
        return _redirect_by_role(request.session.get('role'))

    if request.method == 'POST':
        username_input = request.POST.get('username', '').strip()
        password_input = request.POST.get('password', '')

        # 2. Cari user di DB berdasarkan username/NIS/NIP tanpa memfilter role
        user = Users.objects.filter(username=username_input).first()

        # Fallback: Jika tidak ketemu di Users, cari lewat NIS (Siswa) / NIP (Kesiswaan)
        if not user:
            siswa_obj = Siswa.objects.filter(nis=username_input).first()
            if siswa_obj:
                user = siswa_obj.users
            else:
                kesiswaan_obj = Kesiswaan.objects.filter(nip=username_input).first()
                if kesiswaan_obj:
                    user = kesiswaan_obj.user

        # 3. Validasi Keberadaan User & Password
        if user is None or not check_password(password_input, user.password):
            messages.error(request, 'Username / NIS / NIP atau password salah.')
            return render(request, 'eprestasi/login.html')

        # =========================================================
        # CARI NAMA LENGKAP DARI TABEL PROFIL BERDASARKAN ROLE
        # =========================================================
        nama_tampil = user.username  # Default fallback jika profil belum diisi

        if user.role == 'siswa':
            profil = Siswa.objects.filter(users=user).first()
            if profil and profil.nama:
                nama_tampil = profil.nama

        elif user.role in ('kesiswaan', 'admin', 'super_admin'):
            profil = Kesiswaan.objects.filter(user=user).first()
            if profil and profil.nama:
                nama_tampil = profil.nama

        # =========================================================
        # SIMPAN IDENTITAS KE SESSION
        # =========================================================
        request.session['user_id'] = user.id
        request.session['username'] = user.username
        request.session['role'] = user.role
        request.session['nama'] = nama_tampil

        messages.success(request, f'Selamat datang, {nama_tampil}!')
        
        # 4. Redirect otomatis ke dashboard sesuai role asli di DB
        return _redirect_by_role(user.role)

    return render(request, 'eprestasi/login.html')


def logout_view(request):
    request.session.flush()  # Hapus semua data session
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