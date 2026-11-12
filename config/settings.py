"""
Django settings for config project.
"""

import os
from pathlib import Path
from dotenv import load_dotenv
import resend
# Load environment variables dari file .env
load_dotenv()

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = BASE_DIR / 'templates'

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.environ.get('SECRET_KEY', 'django-insecure-#zd^1((1@f6wx87z!2g*u5080_8lm36kax9e6h#hu-l*fv&q@d')

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = os.environ.get("DEBUG", "False").lower() == "true"


ALLOWED_HOSTS = [
    'localhost',
    'eprestasi.freznx.my.id',
    '127.0.0.1',
    '.vercel.app',  # Menjangkau seluruh subdomain *.vercel.app
]

# Application definition
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'cloudinary_storage',  # Harus diletakkan sebelum staticfiles
    'cloudinary',
    'eprestasi',
    'resend',  # Tambahkan aplikasi Resend
]

# Un-comment baris di bawah jika Anda menggunakan custom user model:
# AUTH_USER_MODEL = 'eprestasi.Users'

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',  # Posisi tepat di bawah SecurityMiddleware
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'eprestasi.middleware.ErrorPageMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

# ==========================================
# KONFIGURASI CORS & COOKIE (DEVELOPMENT & PROD)
# ==========================================

# 1. Izinkan frontend mengirim cookie/session

# 2. Daftarkan URL/Port tempat Frontend kamu berjalan
# 3. Gabungan domain trusted origin untuk CSRF
CSRF_TRUSTED_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "https://*.vercel.app",
    "https://eprestasi.freznx.my.id",
]
CSRF_FAILURE_VIEW = 'eprestasi.error_views.csrf_failure'

# 4. Pengaturan Cookie untuk HTTP (localhost)
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
SESSION_COOKIE_SAMESITE = 'Lax'
CSRF_COOKIE_SAMESITE = 'Lax'



ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [TEMPLATES_DIR],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'eprestasi.context_processors.notifikasi_kesiswaan',   # <- tambahan
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

# Database (Supabase PostgreSQL)
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.environ.get('DB_NAME', ''),
        'USER': os.environ.get('DB_USER', ''),
        'PASSWORD': os.environ.get('DB_PASSWORD', ''),
        'HOST': os.environ.get('DB_HOST', ''),
        'PORT': os.environ.get('DB_PORT', ''),
    }
}

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

# Internationalization
LANGUAGE_CODE = 'id-id'
TIME_ZONE = 'Asia/Jakarta'
USE_I18N = True
USE_TZ = True

# ==============================================================================
# STATIC FILES (CSS, JavaScript, Images)
# ==============================================================================
# STATIC FILES
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

STATICFILES_DIRS = [
    BASE_DIR /"eprestasi" / "static",
]

# MEDIA & STATIC STORAGE
STORAGES = {
    "default": {
        "BACKEND": "cloudinary_storage.storage.MediaCloudinaryStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedStaticFilesStorage",
    },
}
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"
# CLOUDINARY
CLOUDINARY_STORAGE = {
    "CLOUDINARY_URL": os.environ.get("CLOUDINARY_URL"),
}# settings.py

# ==== Email (OTP lupa password) ====

# ==== Email (OTP lupa password) ====

RESEND_API_KEY = os.environ.get('RESEND_API', '')
RESEND_FROM_EMAIL = os.environ.get(
    'RESEND_FROM_EMAIL',
    'E-Prestasi <noreply@eprestasi.freznx.my.id>'
)

# ==== OTP ke no HP (WhatsApp via Fonnte) ====
OTP_HP_PROVIDER = os.environ.get('OTP_HP_PROVIDER', 'console')
FONNTE_TOKEN = os.environ.get('FONNTE_TOKEN', '')