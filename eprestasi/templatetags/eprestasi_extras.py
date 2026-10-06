"""
Template tag kecil yang dipakai bersama oleh semua halaman admin yang punya
kombinasi search + filter + sorting + pagination (Kelulusan & Alumni, Log
Aktivitas, Kelola User, Tahun Ajaran, Pengelolaan Kelas, dst).

Dibuat supaya tautan sort/paginasi selalu MEMPERTAHANKAN seluruh parameter
GET yang sedang aktif (search, filter, dsb) -- tidak pernah kembali ke
default saat pindah halaman atau ganti urutan.
"""
from django import template

register = template.Library()


@register.simple_tag(takes_context=True)
def url_replace(context, **kwargs):
    """
    Kembalikan querystring saat ini dengan sebagian parameter diganti/dihapus.

    Contoh pemakaian di template:
        <a href="?{% url_replace sort='nama_asc' %}">Nama</a>
        <a href="?{% url_replace page=3 %}">3</a>

    Aturan:
    - Parameter yang value-nya '' atau None akan DIHAPUS dari querystring.
    - Kalau yang diubah BUKAN 'page', maka 'page' otomatis direset (dibuang)
      supaya user selalu diarahkan ke halaman 1 saat filter/sort berubah.
    """
    request = context['request']
    query = request.GET.copy()

    for key, value in kwargs.items():
        if value is None or value == '':
            query.pop(key, None)
        else:
            query[key] = value

    if 'page' not in kwargs:
        query.pop('page', None)

    return query.urlencode()


@register.simple_tag
def page_range(page_obj, window=1):
    """
    Bangun daftar nomor halaman untuk ditampilkan sebagai pill pagination,
    dengan '...' (None) di tempat yang ada lompatan.
    Pola: 1 ... [current-window .. current+window] ... last
    Dipakai lewat: {% page_range page_obj as pages %}
    """
    total = page_obj.paginator.num_pages
    current = page_obj.number
    pages = []
    for p in range(1, total + 1):
        if p == 1 or p == total or (current - window <= p <= current + window):
            pages.append(p)
        elif not pages or pages[-1] is not None:
            pages.append(None)
    return pages


@register.simple_tag(takes_context=True)
def sort_icon(context, current_sort, asc_key, desc_key):
    """
    Ikon indikator arah sorting untuk header kolom tabel.
    current_sort: value sort yang sedang aktif (dari request.GET).
    asc_key/desc_key: value sort utk arah naik/turun kolom ini.
    """
    if current_sort == asc_key:
        return 'bi-sort-up'
    if current_sort == desc_key:
        return 'bi-sort-down'
    return 'bi-arrow-down-up text-muted'
