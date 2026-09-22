from functools import wraps
from django.shortcuts import redirect   
from django.contrib import messages

def login (view_func):
    @wraps (view_func)
    def wrapper(request, *args, **kwargs):
        if request.session.get('role')!= 'admin':
            return redirect('login')
        
        return view_func(request, *args,**kwargs)
    return wrapper

def role_required(*allowed_roles):
    def decorator(view_func):
        @wraps (view_func)
        def wrapper(request, *args, **kwargs):
            if not request.session.get('user_id'):
                messages.warning(request,'Anda harus login terlebih dahulu !')
                return redirect('login')
            if request.session.get('role')not in allowed_roles:
                messages.warning(request,'Anda tidak memiliki izin untuk mengakses halaman ini !')
                return redirect('login')
            return view_func(request, *args, **kwargs)
        return wrapper
    return decorator
