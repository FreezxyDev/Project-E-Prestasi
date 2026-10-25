"""
Helper OTP untuk fitur Lupa Password.

- Kode 6 digit, berlaku 10 menit, SEKALI pakai. Yang disimpan di database hanya
  HMAC-nya (bukan kode mentah).
- Pengiriman:
    * Email  -> django.core.mail.send_mail (butuh EMAIL_* di settings.py)
    * No HP  -> dikirim lewat WhatsApp (Fonnte) kalau OTP_HP_PROVIDER = 'fonnte'.
                Provider 'console' (default) hanya menulis kode ke log server --
                CUMA untuk pengembangan, siswa tidak menerima apa-apa.
  Pengaturan lengkap ada di PENGATURAN_OTP.md.
"""
import hashlib
import hmac
import json
import logging
import re
import secrets
import urllib.error
import urllib.parse
import urllib.request
from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone

logger = logging.getLogger(__name__)

PANJANG_OTP = 6
MASA_BERLAKU_OTP = timedelta(minutes=10)
JEDA_KIRIM_ULANG = timedelta(seconds=60)   # jarak minimal antar pengiriman
MAKS_KIRIM_PER_JAM = 5                     # batas pengiriman OTP per akun per jam
MAKS_SALAH_PER_OTP = 5                     # salah ketik sebanyak ini -> OTP hangus


def buat_kode():
    return ''.join(secrets.choice('0123456789') for _ in range(PANJANG_OTP))


def hash_kode(user_id, kode):
    """HMAC kode + id user, supaya kode yang sama milik dua akun hasilnya beda."""
    kunci = settings.SECRET_KEY.encode('utf-8')
    pesan = f'{user_id}:{kode}'.encode('utf-8')
    return hmac.new(kunci, pesan, hashlib.sha256).hexdigest()


def cocok(user_id, kode, kode_hash):
    return hmac.compare_digest(hash_kode(user_id, kode), kode_hash)


# ---------------------------------------------------------------------------
# Masking & normalisasi
# ---------------------------------------------------------------------------
def samarkan_email(email):
    """budi.santoso@gmail.com -> bu***@gmail.com"""
    email = (email or '').strip()
    if '@' not in email:
        return '***'
    lokal, domain = email.split('@', 1)
    return f'{lokal[:2]}***@{domain}'


def samarkan_hp(no_hp):
    """081234567890 -> 0812*****890"""
    digit = re.sub(r'\D', '', no_hp or '')
    if len(digit) < 8:
        return '*' * len(digit)
    return f'{digit[:4]}{"*" * (len(digit) - 7)}{digit[-3:]}'


def normalisasi_hp(no_hp):
    """081234567890 / +6281234567890 / 6281234567890 -> 6281234567890"""
    digit = re.sub(r'\D', '', no_hp or '')
    if digit.startswith('0'):
        digit = '62' + digit[1:]
    elif digit.startswith('8'):
        digit = '62' + digit
    return digit


# ---------------------------------------------------------------------------
# Pengiriman
# ---------------------------------------------------------------------------
def _pesan(kode, nama):
    menit = int(MASA_BERLAKU_OTP.total_seconds() // 60)
    return (
        f'Halo {nama},\n\n'
        f'Kode OTP reset password E-Prestasi SMKN 11 Bandung kamu: {kode}\n'
        f'Berlaku {menit} menit dan hanya bisa dipakai sekali.\n\n'
        f'Jangan bagikan kode ini ke siapa pun. Kalau kamu tidak merasa meminta reset '
        f'password, abaikan pesan ini.'
    )


def kirim_otp_email(email, kode, nama):
    """Return True kalau berhasil dikirim."""
    try:
        send_mail(
            subject='Kode OTP Reset Password - E-Prestasi',
            message=_pesan(kode, nama),
            from_email=None,
            recipient_list=[email],
            fail_silently=False,
        )
        return True
    except Exception:
        logger.exception('Gagal mengirim OTP lewat email ke %s', samarkan_email(email))
        return False


def kirim_otp_hp(no_hp, kode, nama):
    """Return True kalau berhasil dikirim."""
    provider = getattr(settings, 'OTP_HP_PROVIDER', 'console')
    target = normalisasi_hp(no_hp)
    if not target:
        return False

    if provider == 'fonnte':
        token = getattr(settings, 'FONNTE_TOKEN', '')
        if not token:
            logger.error('OTP_HP_PROVIDER=fonnte tapi FONNTE_TOKEN belum diisi di settings.')
            return False
        try:
            data = urllib.parse.urlencode({
                'target': target,
                'message': _pesan(kode, nama),
                'countryCode': '62',
            }).encode('utf-8')
            req = urllib.request.Request(
                'https://api.fonnte.com/send', data=data,
                headers={'Authorization': token}, method='POST',
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                hasil = json.loads(resp.read().decode('utf-8') or '{}')
            if hasil.get('status') is True:
                return True
            logger.error('Fonnte menolak pengiriman OTP: %s', hasil.get('reason') or hasil)
            return False
        except (urllib.error.URLError, ValueError, TimeoutError):
            logger.exception('Gagal mengirim OTP lewat Fonnte ke %s', samarkan_hp(no_hp))
            return False

    # Provider 'console': hanya untuk pengembangan.
    logger.warning('[OTP console] Kode untuk %s: %s', samarkan_hp(no_hp), kode)
    return bool(getattr(settings, 'DEBUG', False))
