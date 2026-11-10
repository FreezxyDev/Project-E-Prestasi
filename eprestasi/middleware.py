"""
ErrorPageMiddleware: jaring pengaman supaya pengguna TIDAK PERNAH melihat halaman
error bawaan Django.

1. Exception yang tidak tertangani di view mana pun -> dicatat ke log lengkap dengan
   ID referensi -> halaman 500 bertema (atau 503 bila database tidak tersedia,
   413 bila unggahan terlalu besar).
2. Response error polos (404/403/405/400/dst, mis. HttpResponseForbidden("...") atau
   HttpResponseNotAllowed dari @require_POST) -> diganti halaman bertema.

Saat DEBUG=True middleware ini tidak aktif, supaya developer tetap melihat halaman
debug Django yang lengkap. Untuk memaksa aktif di DEBUG: EPRESTASI_ERROR_PAGES_IN_DEBUG = True.
Letakkan PALING BAWAH di MIDDLEWARE agar menangkap exception dari middleware lain.
"""
import logging

from django.conf import settings
from django.core.exceptions import PermissionDenied, RequestDataTooBig, SuspiciousOperation
from django.db.utils import InterfaceError, OperationalError
from django.http import Http404

from .error_views import buat_ref, buat_response_error

logger = logging.getLogger(__name__)


def _aktif():
    return (not settings.DEBUG) or getattr(settings, 'EPRESTASI_ERROR_PAGES_IN_DEBUG', False)


class ErrorPageMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if not _aktif():
            return response
        return self._ganti_jika_polos(request, response)

    def process_exception(self, request, exception):
        if not _aktif():
            return None
        # Biarkan Django mengubah exception "bermakna" ini jadi 404/403/400;
        # hasilnya ditangkap lagi di __call__ dan dipakaikan tema.
        if isinstance(exception, RequestDataTooBig):
            logger.warning('Unggahan terlalu besar: %s', request.path)
            return buat_response_error(request, 413)
        if isinstance(exception, (Http404, PermissionDenied, SuspiciousOperation)):
            return None

        ref = buat_ref()
        logger.error('Exception tidak tertangani [ref=%s] %s %s', ref,
                     request.method, request.get_full_path(), exc_info=exception)
        if isinstance(exception, (OperationalError, InterfaceError)):
            return buat_response_error(request, 503, ref=ref)
        return buat_response_error(request, 500, ref=ref)

    @staticmethod
    def _ganti_jika_polos(request, response):
        status = response.status_code
        if status < 400 or getattr(response, '_eprestasi_error_page', False):
            return response
        if getattr(response, 'streaming', False):
            return response
        tipe = response.get('Content-Type', '')
        # Jangan menimpa JSON/file/redirect buatan view sendiri; hanya halaman HTML.
        if 'text/html' not in tipe:
            return response
        ref = buat_ref() if status >= 500 else None
        if ref:
            logger.error('Response %s [ref=%s] %s', status, ref, request.get_full_path())
        return buat_response_error(request, status, ref=ref)
