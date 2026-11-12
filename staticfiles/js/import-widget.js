/* =====================================================================
   import-widget.js - kartu progres import siswa yang muncul di SEMUA halaman admin.
   - Import dimulai dari form #formImport (halaman Import Siswa), lalu kartu kecil di pojok kanan bawah
     menampilkan progres. Kartu tetap ada walau admin berpindah halaman.
   - Proses digerakkan browser per batch (/proses/). Tiap halaman baru membaca /status/ dan menyambung
     proses yang sedang berjalan. Hanya satu tab yang menggerakkan proses (kunci di localStorage).
   - Tombol Batal -> dialog peringatan -> /batal/. Siswa yang sudah dibuat tetap tersimpan.
   ===================================================================== */
(function () {
    'use strict';
    var root = document.getElementById('importWidget');
    if (!root || !window.fetch) { return; }

    var url = { mulai: root.dataset.urlMulai, proses: root.dataset.urlProses, batal: root.dataset.urlBatal,
                status: root.dataset.urlStatus, tutup: root.dataset.urlTutup, hasil: root.dataset.urlHasil };
    var csrf = root.dataset.csrf;
    var KUNCI = 'eprestasi_import_kunci', STALE = 5000;
    var id = Math.random().toString(36).slice(2);
    var lastSt = null, info = null, driver = false, loopJalan = false, minta_batal = false, pollTimer = null;

    var $ = function (s) { return root.querySelector(s); };
    var el = { card: $('.impw-card'), ic: $('.impw-ic'), judul: $('.impw-title'), sub: $('.impw-sub'),
               angka: $('.impw-num'), pct: $('.impw-pct'), fill: $('.impw-fill'), track: $('.impw-track'),
               note: $('.impw-note'), detail: $('.impw-detail'), aksi: $('.impw-actions'), tutup: $('.impw-close'),
               confirm: $('.impw-confirm'), confirmText: $('.impw-confirm-text') };

    function ikon(n) { return '<i class="bi ' + n + '"></i>'; }
    function post(alamat, data) {
        var body = data || new URLSearchParams();
        if (body.append && !body.has('csrfmiddlewaretoken')) { body.append('csrfmiddlewaretoken', csrf); }
        return fetch(alamat, { method: 'POST', body: body, headers: { 'X-Requested-With': 'XMLHttpRequest' }, credentials: 'same-origin' })
            .then(function (r) { return r.json().catch(function () { return { ok: false, error: 'Respons server tidak dikenali.' }; })
                .then(function (j) { j._status = r.status; return j; }); });
    }
    function ambilStatus() {
        return fetch(url.status, { headers: { 'X-Requested-With': 'XMLHttpRequest' }, credentials: 'same-origin' })
            .then(function (r) { return r.json(); });
    }

    // ---- kunci pengemudi antar tab ----
    function bacaKunci() { try { return JSON.parse(localStorage.getItem(KUNCI) || 'null'); } catch (e) { return null; } }
    function pegangKunci() {
        try {
            var k = bacaKunci();
            if (k && k.id !== id && Date.now() - k.t < STALE) { return false; }
            localStorage.setItem(KUNCI, JSON.stringify({ id: id, t: Date.now() }));
        } catch (e) { /* tanpa localStorage: anggap boleh */ }
        return true;
    }
    function lepasKunci() { try { var k = bacaKunci(); if (k && k.id === id) { localStorage.removeItem(KUNCI); } } catch (e) {} }

    // ---- tampilan ----
    function tampil(boleh) { root.hidden = !boleh; if (boleh) { requestAnimationFrame(function () { root.classList.add('is-open'); }); } else { root.classList.remove('is-open'); } }
    function persen(i) { return i && i.total ? Math.min(100, Math.floor(i.diproses * 100 / i.total)) : 0; }

    function butir(kelas, ic, html) { return '<div class="impw-item ' + kelas + '">' + ikon(ic) + '<span>' + html + '</span></div>'; }

    function render() {
        if (!info || !info.aktif) { tampil(false); return; }
        var p = persen(info);
        el.angka.textContent = info.diproses + ' / ' + info.total + ' siswa';
        el.pct.textContent = p + '%';
        el.fill.style.width = p + '%';
        el.track.setAttribute('aria-valuenow', p);
        var st = info.state;
        el.card.dataset.status = st === 'jalan' ? 'proses' : (st === 'selesai' ? 'selesai' : 'batal');
        el.tutup.hidden = st === 'jalan';
        el.note.hidden = st !== 'jalan';
        var ganti = st !== lastSt; lastSt = st;
        if (ganti) { el.detail.innerHTML = ''; el.aksi.innerHTML = ''; }

        if (st === 'jalan') {
            el.ic.innerHTML = ikon('bi-cloud-arrow-up-fill');
            el.judul.textContent = 'Mengimpor data siswa';
            el.sub.textContent = driver || minta_batal ? (minta_batal ? 'Menghentikan setelah batch ini...' : 'Memproses baris ' + info.diproses + ' dari ' + info.total) : 'Menyambungkan proses...';
            if (ganti) { el.aksi.innerHTML = '<button type="button" class="impw-btn impw-btn-ghost" data-act="batal">' + ikon('bi-x-lg') + ' Batalkan</button>'; }
        } else if (st === 'selesai') {
            var baru = info.berhasil > 0;
            el.ic.innerHTML = ikon(baru ? 'bi-check-circle-fill' : 'bi-exclamation-triangle-fill');
            el.judul.textContent = baru ? 'Upload siswa berhasil' : 'Selesai, tidak ada siswa baru';
            el.sub.textContent = baru ? info.berhasil + ' akun siswa ditambahkan.' : 'Semua baris dilewati.';
            var h = '';
            if (info.password_otomatis > 0) { h += butir('is-key', 'bi-key-fill', '<b>' + info.password_otomatis + ' password</b> dibuat otomatis karena kosong di Excel.'); }
            if (info.gagal > 0) { h += butir('is-skip', 'bi-exclamation-circle-fill', '<b>' + info.gagal + ' baris</b> dilewati.'); }
            if (baru) { h += butir('', 'bi-info-circle-fill', 'Password hanya bisa dilihat di halaman detail.'); }
            if (ganti) { el.detail.innerHTML = h; el.aksi.innerHTML = info.password_otomatis > 0
                ? '<a class="impw-btn impw-btn-main" href="' + url.hasil + '?filter=otomatis">' + ikon('bi-key-fill') + ' Lihat Akun Password Otomatis (' + info.password_otomatis + ')</a>' + '<a class="impw-btn impw-btn-ghost" href="' + url.hasil + '">Semua Hasil</a>'
                : '<a class="impw-btn impw-btn-main" href="' + url.hasil + '">' + ikon('bi-card-checklist') + ' Lihat Detail</a>'; }
        } else {
            el.ic.innerHTML = ikon('bi-slash-circle-fill');
            el.judul.textContent = 'Import dihentikan';
            el.sub.textContent = info.berhasil + ' siswa sudah tersimpan, sisanya tidak diimpor.';
            if (ganti && info.berhasil + info.gagal > 0) { el.aksi.innerHTML = '<a class="impw-btn impw-btn-main" href="' + url.hasil + '">' + ikon('bi-card-checklist') + ' Lihat Hasil Sementara</a>'; }
        }
        tampil(true);
    }

    // ---- pengemudi: proses per batch ----
    function loop() {
        if (loopJalan) { return; }
        loopJalan = true; driver = true;
        (function langkah() {
            if (!info || info.state !== 'jalan') { loopJalan = false; lepasKunci(); return; }
            if (minta_batal) {
                post(url.batal).then(function () { minta_batal = false; loopJalan = false; lepasKunci(); sinkron(); });
                return;
            }
            if (!pegangKunci()) { loopJalan = false; driver = false; mulaiPoll(); return; }
            post(url.proses, new URLSearchParams({ token: info.token, posisi: info.diproses })).then(function (d) {
                if (!d.ok) { loopJalan = false; lepasKunci(); sinkron(); return; }   // 409: dibatalkan dari tab lain
                var tadi = info.state;
                info = { aktif: true, token: info.token, state: d.selesai ? 'selesai' : 'jalan', total: d.total, diproses: d.diproses,
                         berhasil: d.berhasil, gagal: d.gagal, password_otomatis: d.password_otomatis };
                render();
                if (d.selesai) {
                    loopJalan = false; lepasKunci();
                    if (window.toast && tadi === 'jalan') { toast.success('Import siswa selesai.'); }
                } else { langkah(); }
            }).catch(function () {
                loopJalan = false; lepasKunci();
                if (window.toast) { toast.error('Koneksi terputus. Proses akan dilanjutkan otomatis.'); }
                setTimeout(sinkron, 3000);
            });
        })();
    }

    // ---- sinkron dengan server / ikuti tab lain ----
    function sinkron() {
        return ambilStatus().then(function (d) {
            info = d; render();
            if (d.aktif && d.state === 'jalan') {
                if (!loopJalan) { if (pegangKunci()) { loop(); } else { driver = false; render(); mulaiPoll(); } }
            } else { berhentiPoll(); }
        }).catch(function () { /* diam: coba lagi di poll berikut */ });
    }
    function mulaiPoll() { if (!pollTimer) { pollTimer = setInterval(sinkron, 1500); } }
    function berhentiPoll() { if (pollTimer) { clearInterval(pollTimer); pollTimer = null; } }

    // ---- aksi ----
    function bukaKonfirmasi() {
        var n = info ? info.berhasil : 0;
        el.confirmText.innerHTML = 'Import akan <b>dihentikan</b>. ' + (n > 0 ? '<b>' + n + ' siswa</b> yang sudah terupload tetap tersimpan, ' : 'Siswa yang sudah terupload tetap tersimpan, ') + 'tetapi sisa siswa yang belum diproses <b>tidak akan diimpor</b>.';
        el.confirm.hidden = false;
        var b = el.confirm.querySelector('[data-act="lanjut"]'); if (b) { b.focus(); }
    }
    root.addEventListener('click', function (e) {
        var t = e.target.closest('[data-act]'); if (!t) { return; }
        var a = t.dataset.act;
        if (a === 'batal') { bukaKonfirmasi(); }
        else if (a === 'lanjut') { el.confirm.hidden = true; }
        else if (a === 'stop') {
            el.confirm.hidden = true; minta_batal = true; render();
            if (!loopJalan) { post(url.batal).then(function () { minta_batal = false; sinkron(); }); }
        }
        else if (a === 'tutup') { post(url.tutup).then(function () { info = null; tampil(false); }); }
    });
    document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && !el.confirm.hidden) { el.confirm.hidden = true; } });

    // ---- mulai dari form halaman Import Siswa ----
    var form = document.getElementById('formImport');
    if (form) {
        form.addEventListener('submit', function (e) {
            var f = form.querySelector('input[type=file]');
            e.preventDefault();
            if (info && info.aktif && info.state === 'jalan') { if (window.toast) { toast.warning('Masih ada import yang berjalan.'); } return; }
            if (!f || !f.files.length) { if (window.toast) { toast.error('Pilih file Excel (.xlsx) terlebih dahulu.'); } return; }
            var btn = form.querySelector('button[type=submit]'); if (btn) { btn.disabled = true; }
            post(url.mulai, new FormData(form)).then(function (d) {
                if (btn) { btn.disabled = false; }
                if (!d.ok) { if (window.toast) { toast.error(d.error || 'File tidak dapat diproses.'); } return; }
                form.reset(); minta_batal = false;
                info = { aktif: true, token: d.token, state: 'jalan', total: d.total, diproses: 0, berhasil: 0, gagal: 0, password_otomatis: 0 };
                render(); loop();
            }).catch(function () { if (btn) { btn.disabled = false; } if (window.toast) { toast.error('Tidak dapat menghubungi server.'); } });
        });
    }

    // Kunci sengaja TIDAK dilepas saat halaman ditutup: halaman baru menunggu sampai batch yang sedang
    // berjalan di server selesai (kunci kedaluwarsa), supaya satu batch tidak diproses dua kali.
    sinkron();
})();