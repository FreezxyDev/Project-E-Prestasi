from functools import wraps
from django.shortcuts import redirect   
from django.contrib import messages

from .models import Users, Siswa, NPSN_SMKN_11_BANDUNG

def login (view_func):
    @wraps (view_func)
    def wrapper(request, *args, **kwargs):
        if request.session.get('role')!= 'admin':
            return redirect('login')
        
        return view_func(request, *args,**kwargs)
    return wrapper

def role_required(*allowed_roles, allow_nonaktif=False):
    """
    allow_nonaktif=True -> view ini boleh dibuka siswa NONAKTIF (siswa yang sudah
    keluar/dikeluarkan). Tanpa itu, siswa nonaktif yang membuka view ini dialihkan
    ke halaman QR Code (satu-satunya halaman portal yang boleh mereka pakai).
    """
    def decorator(view_func):
        @wraps (view_func)
        def wrapper(request, *args, **kwargs):
            if not request.session.get('user_id'):
                messages.warning(request,'Anda harus login terlebih dahulu !')
                return redirect('login')
            user_id = request.session.get('user_id')
            user = Users.objects.filter(id=user_id).first()
            if user is None:
                request.session.flush()
                return redirect('login')

            # Siswa NONAKTIF (keluar/dikeluarkan): boleh login, tapi hanya ke halaman
            # yang ditandai allow_nonaktif (QR Code / portofolio). Upload, riwayat,
            # profil, dan lainnya diblokir.
            siswa_nonaktif = (
                user.role == 'siswa'
                and Siswa.objects.filter(users_id=user.id, status='keluar').exists()
            )
            if siswa_nonaktif:
                if request.session.get('role') not in allowed_roles:
                    messages.warning(request,'Anda tidak memiliki izin untuk mengakses halaman ini !')
                    return redirect('login')
                if not allow_nonaktif:
                    messages.warning(
                        request,
                        'Akun Anda berstatus siswa nonaktif. Anda hanya bisa mengakses QR Code '
                        'dan halaman portofolio.'
                    )
                    return redirect('siswa_qr_code')
                return view_func(request, *args, **kwargs)

            # Akun lain yang NPSN-nya tidak valid langsung dikeluarkan dari sesi yang
            # masih berjalan, bukan menunggu sesi habis.
            if not user.anggota_sekolah_valid:
                request.session.flush()
                messages.error(request, 'Akun ini tidak terafiliasi dengan SMKN 11 Bandung.')
                return redirect('login')
            if request.session.get('role')not in allowed_roles:
                messages.warning(request,'Anda tidak memiliki izin untuk mengakses halaman ini !')
                return redirect('login')
            return view_func(request, *args, **kwargs)
        return wrapper
    return decorator
