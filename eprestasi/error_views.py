"""
Halaman error kustom E-Prestasi (400, 403, 404, 405, 413, 500, 503, dst).

Tujuannya: pengguna tidak pernah melihat halaman error bawaan Django. Yang tampil
adalah halaman bertema E-Prestasi berisi kode error, penjelasan singkat, dan tombol
kembali. Untuk error 500, setiap kejadian diberi ID referensi yang sama dengan yang
dicatat di log server, sehingga admin bisa mencari penyebabnya dari ID itu.

Cara pasang: lihat README_ERROR_PAGES.md.
"""
import logging
import uuid

from django.http import HttpResponse, JsonResponse
from django.template.loader import render_to_string
from django.urls import NoReverseMatch, reverse

logger = logging.getLogger(__name__)

TEMPLATE = 'eprestasi/errors/error.html'

# kode -> (judul, penjelasan, ikon bootstrap-icons)
PESAN = {
    400: ('Permintaan Tidak Valid',
          'Permintaan yang dikirim tidak dapat diproses. Periksa kembali data yang Anda isi, lalu coba lagi.',
          'bi-exclamation-triangle'),
    401: ('Perlu Login',
          'Anda harus login terlebih dahulu untuk mengakses halaman ini.',
          'bi-person-lock'),
    403: ('Akses Ditolak',
          'Anda tidak memiliki izin untuk membuka halaman ini. Jika merasa ini keliru, hubungi admin sekolah.',
          'bi-shield-lock'),
    404: ('Halaman Tidak Ditemukan',
          'Halaman yang Anda cari tidak ada, sudah dipindahkan, atau tautannya salah.',
          'bi-compass'),
    405: ('Metode Tidak Diizinkan',
          'Halaman ini tidak dapat dibuka dengan cara tersebut. Silakan kembali dan gunakan tombol atau tautan yang tersedia.',
          'bi-slash-circle'),
    408: ('Waktu Permintaan Habis',
          'Permintaan Anda terlalu lama diproses. Periksa koneksi internet lalu coba lagi.',
          'bi-hourglass-split'),
    413: ('Berkas Terlalu Besar',
          'Ukuran berkas atau data yang Anda kirim melebihi batas yang diizinkan. Perkecil ukurannya lalu coba lagi.',
          'bi-file-earmark-arrow-up'),
    429: ('Terlalu Banyak Permintaan',
          'Anda mengirim terlalu banyak permintaan dalam waktu singkat. Tunggu beberapa saat lalu coba lagi.',
          'bi-speedometer2'),
    500: ('Terjadi Kesalahan pada Server',
          'Maaf, terjadi kesalahan di sisi kami. Kesalahan ini sudah dicatat dan akan segera diperbaiki. Silakan coba lagi beberapa saat lagi.',
          'bi-bug'),
    502: ('Gateway Bermasalah',
          'Server sedang mengalami gangguan koneksi. Silakan coba lagi beberapa saat lagi.',
          'bi-hdd-network'),
    503: ('Layanan Sedang Tidak Tersedia',
          'Layanan sedang sibuk atau dalam pemeliharaan. Silakan coba lagi beberapa saat lagi.',
          'bi-tools'),
    504: ('Server Tidak Merespons',
          'Server terlalu lama merespons. Silakan coba lagi beberapa saat lagi.',
          'bi-clock-history'),
}


def _judul_default(status):
    return ('Terjadi Kesalahan', 'Terjadi kesalahan saat memproses permintaan Anda.',
            'bi-exclamation-octagon')


def _tautan_beranda(request):
    """(url, label). Pengguna yang sudah login dibawa ke dashboard sesuai role-nya."""
    role = None
    try:
        role = request.session.get('role') if request is not None else None
    except Exception:
        role = None  # sesi/DB bermasalah: jangan sampai halaman error ikut error
    nama = {
        'admin': 'dashboard', 'super_admin': 'dashboard',
        'siswa': 'siswa_dashboard', 'kesiswaan': 'kesiswaan_dashboard',
    }.get(role)
    try:
        if nama:
            return reverse(nama), 'Kembali ke Dashboard'
        return reverse('landing_page'), 'Kembali ke Beranda'
    except NoReverseMatch:
        return '/', 'Kembali ke Beranda'


def _minta_json(request):
    """True untuk request AJAX/API, supaya JavaScript menerima JSON (bukan HTML)."""
    if request is None:
        return False
    try:
        accept = request.headers.get('Accept', '')
        return (
            request.headers.get('X-Requested-With') == 'XMLHttpRequest'
            or request.path.startswith('/api/')
            or ('application/json' in accept and 'text/html' not in accept)
        )
    except Exception:
        return False


def buat_response_error(request, status, pesan=None, ref=None):
    """Bangun response error bertema untuk kode `status`. Tidak pernah melempar error."""
    judul, penjelasan, ikon = PESAN.get(status) or _judul_default(status)
    if pesan:
        penjelasan = pesan

    if _minta_json(request):
        data = {'ok': False, 'status': status, 'error': judul, 'detail': penjelasan}
        if ref:
            data['ref'] = ref
        resp = JsonResponse(data, status=status)
        resp._eprestasi_error_page = True
        return resp

    url, label = _tautan_beranda(request)
    konteks = {
        'kode': status, 'judul': judul, 'penjelasan': penjelasan, 'ikon': ikon,
        'ref': ref, 'url_beranda': url, 'label_beranda': label,
        # tombol "Kembali" hanya berguna untuk error yang bisa diperbaiki pengguna
        'bisa_kembali': status < 500,
        'bisa_coba_lagi': status >= 500,
    }
    try:
        # Sengaja TANPA request: context processor menyentuh database, padahal
        # error bisa saja berasal dari database itu sendiri.
        html = render_to_string(TEMPLATE, konteks)
    except Exception:  # template rusak pun tidak boleh membuat error berlapis
        logger.exception('Gagal merender halaman error %s', status)
        html = (f'<h1>{status} - {judul}</h1><p>{penjelasan}</p>'
                f'<p><a href="{url}">{label}</a></p>')
    resp = HttpResponse(html, status=status)
    resp._eprestasi_error_page = True
    return resp


def buat_ref():
    return uuid.uuid4().hex[:8].upper()


# ---- Handler yang didaftarkan di urls.py project (handler400, dst) ----
def error_400(request, exception=None):
    return buat_response_error(request, 400)


def error_403(request, exception=None):
    return buat_response_error(request, 403)


def error_404(request, exception=None):
    return buat_response_error(request, 404)


def error_500(request):
    ref = buat_ref()
    logger.error('Server error 500 [ref=%s] path=%s', ref,
                 getattr(request, 'path', '?'), exc_info=True)
    return buat_response_error(request, 500, ref=ref)


def csrf_failure(request, reason=''):
    """Pengganti halaman 403 CSRF bawaan (settings.CSRF_FAILURE_VIEW)."""
    logger.warning('CSRF gagal: %s path=%s', reason, request.path)
    return buat_response_error(
        request, 403,
        pesan='Sesi formulir Anda sudah kedaluwarsa atau tidak valid. '
              'Muat ulang halaman sebelumnya, lalu kirim ulang formulirnya.',
    )


def preview_error(request, kode):
    """Untuk menguji tampilan tiap halaman error. Hanya terdaftar kalau DEBUG=True."""
    return buat_response_error(request, kode, ref='CONTOH123' if kode >= 500 else None)
