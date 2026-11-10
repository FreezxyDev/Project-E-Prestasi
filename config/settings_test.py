"""
Hanya untuk tes lokal tanpa menyentuh database Supabase:
    python manage.py test eprestasi --settings=config.settings_test

Catatan: riwayat migrasi lama (0010 & 0011) sama-sama menambah kolom dokumen_puspresnas,
jadi database KOSONG tidak bisa dibangun dari migrasi. Tes memakai skema dari model langsung
(MIGRATION_MODULES = None) dan URLconf khusus tes (eprestasi/urls_untuk_tes.py).
"""
from .settings import *  # noqa

DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': ':memory:'}}
MIGRATION_MODULES = {'eprestasi': None}
ROOT_URLCONF = 'eprestasi.urls_untuk_tes'
EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'
PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']
