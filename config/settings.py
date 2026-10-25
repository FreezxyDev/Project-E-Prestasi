"""
Django settings for config project.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = BASE_DIR / 'templates'

# ---------------------------------------------------------------------------
# Keamanan: semua rahasia dibaca dari environment variable (Vercel > Settings
# > Environment Variables). Jangan menaruh password/secret key di kode.
# ---------------------------------------------------------------------------
SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-only-key-ganti-di-production')

# DEBUG hanya True kalau env DEBUG=true (lokal). Di Vercel biarkan kosong/False.
DEBUG = os.environ.get('DEBUG', 'False').lower() == 'true'

ALLOWED_HOSTS = [
    'localhost',
    '127.0.0.1',
    'eprestasi.freznx.my.id',
    '.vercel.app',
]

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'cloudinary_storage',  # sebelum staticfiles
    'django.contrib.staticfiles',
    'cloudinary',
    'eprestasi',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',  # tepat setelah Security
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

# ---------------------------------------------------------------------------
# CSRF / cookie / proxy HTTPS
# ---------------------------------------------------------------------------
CSRF_TRUSTED_ORIGINS = [
    'http://localhost:3000',
    'http://127.0.0.1:3000',
    'https://*.vercel.app',
    'https://eprestasi.freznx.my.id',
]

# Vercel berada di belakang proxy HTTPS
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

# Cookie aman di production, longgar di lokal (DEBUG=true)
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
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
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'eprestasi.context_processors.notifikasi_kesiswaan',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

# ---------------------------------------------------------------------------
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.environ.get('DB_NAME', 'postgres'),
        'USER': os.environ.get('DB_USER', 'postgres.ftdtjcvmfhajwxwgeqqk'),
        'PASSWORD': os.environ.get('DB_PASSWORD', ''),  # wajib diisi lewat .env / Vercel
        'HOST': os.environ.get('DB_HOST', 'aws-0-ap-southeast-1.pooler.supabase.com'),
        'PORT': os.environ.get('DB_PORT', '5432'),
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'id-id'
TIME_ZONE = 'Asia/Jakarta'
USE_I18N = True
USE_TZ = True

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# ---------------------------------------------------------------------------
# STATIC FILES - satu folder sumber, tanpa collectstatic, tanpa folder hasil
#   eprestasi/templates/static/css/design.css  ->  /static/css/design.css
# WhiteNoise membaca langsung dari folder sumber (WHITENOISE_USE_FINDERS),
# jadi tidak ada folder staticfiles/ dan tidak ada file .gz.
# ---------------------------------------------------------------------------
STATIC_URL = '/static/'

STATICFILES_DIRS = [
    BASE_DIR / 'eprestasi' / 'templates' / 'static',
]

WHITENOISE_USE_FINDERS = True

# ---------------------------------------------------------------------------
# Cloudinary (media upload) + STORAGES (Django 5.1+)
# ---------------------------------------------------------------------------
CLOUDINARY_STORAGE = {
    'CLOUDINARY_URL': os.environ.get('CLOUDINARY_URL'),
}

STORAGES = {
    'default': {'BACKEND': 'cloudinary_storage.storage.MediaCloudinaryStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
}

# ---------------------------------------------------------------------------
# Email (OTP lupa password)
# ---------------------------------------------------------------------------
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = os.environ.get('EMAIL_HOST', 'smtp.gmail.com')
EMAIL_PORT = int(os.environ.get('EMAIL_PORT', '587'))
EMAIL_USE_TLS = True
EMAIL_USE_SSL = False
EMAIL_TIMEOUT = 15
EMAIL_HOST_USER = os.environ.get('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD', '')
DEFAULT_FROM_EMAIL = EMAIL_HOST_USER

# ---------------------------------------------------------------------------
# OTP ke no HP (WhatsApp via Fonnte)
# ---------------------------------------------------------------------------
OTP_HP_PROVIDER = os.environ.get('OTP_HP_PROVIDER', 'console')
FONNTE_TOKEN = os.environ.get('FONNTE_TOKEN', '')
