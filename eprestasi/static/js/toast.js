/* =====================================================================
   toast.js - notifikasi popup global E-Prestasi (tanpa library).
   - Membaca pesan Django Messages dari #django-messages (di-render _partials/toast.html).
   - API untuk JavaScript/AJAX:  toast.success('...'), toast.error('...'), toast.warning('...'), toast.info('...')
   - Muncul dari kanan, hilang otomatis setelah DURASI ms. Berhenti sebentar saat disorot mouse / fokus.
   ===================================================================== */
(function () {
    'use strict';

    var DURASI = 2000;     // lama tampil (ms)
    var MAKS_TAMPIL = 5;   // maksimal toast sekaligus; sisanya antre
    var JEDA_ANTAR = 140;  // jeda muncul antar toast saat banyak pesan (ms)

    var SVG = {
        success: '<svg viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path fill="currentColor" d="M10 1.8a8.2 8.2 0 1 0 0 16.4 8.2 8.2 0 0 0 0-16.4Zm3.9 6.3-4.4 5a.9.9 0 0 1-1.3.05L6 11.1a.9.9 0 1 1 1.3-1.3l1.5 1.5 3.8-4.3a.9.9 0 1 1 1.3 1.1Z"/></svg>',
        error: '<svg viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path fill="currentColor" d="M10 1.8a8.2 8.2 0 1 0 0 16.4 8.2 8.2 0 0 0 0-16.4Zm3.3 10.2a.9.9 0 1 1-1.3 1.3L10 11.3l-2 2a.9.9 0 1 1-1.3-1.3l2-2-2-2A.9.9 0 1 1 8 6.7l2 2 2-2a.9.9 0 1 1 1.3 1.3l-2 2 2 2Z"/></svg>',
        warning: '<svg viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path fill="currentColor" d="M9.1 3.1a1 1 0 0 1 1.8 0l7 12.6A1 1 0 0 1 17 17.2H3a1 1 0 0 1-.9-1.5l7-12.6ZM10 7.3a.9.9 0 0 0-.9.9v3.2a.9.9 0 1 0 1.8 0V8.2a.9.9 0 0 0-.9-.9Zm0 6.1a1 1 0 1 0 0 2 1 1 0 0 0 0-2Z"/></svg>',
        info: '<svg viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false"><path fill="currentColor" d="M10 1.8a8.2 8.2 0 1 0 0 16.4 8.2 8.2 0 0 0 0-16.4Zm0 3.6a1 1 0 1 1 0 2 1 1 0 0 1 0-2Zm.9 9a.9.9 0 1 1-1.8 0V9.6a.9.9 0 1 1 1.8 0v4.8Z"/></svg>'
    };
    var SVG_TUTUP = '<svg viewBox="0 0 20 20" width="14" height="14" aria-hidden="true" focusable="false"><path fill="currentColor" d="M5.3 4.2 10 8.9l4.7-4.7 1.1 1.1L11.1 10l4.7 4.7-1.1 1.1L10 11.1l-4.7 4.7-1.1-1.1L8.9 10 4.2 5.3z"/></svg>';

    var tampilSekarang = [];   // elemen toast yang sedang tampil
    var antrean = [];          // [{pesan, jenis}] menunggu giliran

    function region() {
        var r = document.getElementById('toast-region');
        if (!r) {
            r = document.createElement('div');
            r.id = 'toast-region';
            r.className = 'toast-region';
            r.setAttribute('aria-live', 'polite');
            r.setAttribute('aria-relevant', 'additions');
            document.body.appendChild(r);
        }
        return r;
    }

    function normalJenis(tag) {
        var t = String(tag || '').split(' ')[0].toLowerCase();
        if (t === 'danger') { t = 'error'; }
        return SVG[t] ? t : 'info';
    }

    function sudahAda(pesan, jenis) {
        return tampilSekarang.some(function (el) { return el.dataset.kunci === jenis + '|' + pesan; })
            || antrean.some(function (q) { return q.jenis === jenis && q.pesan === pesan; });
    }

    function buat(pesan, jenis) {
        var el = document.createElement('div');
        el.className = 'app-toast is-' + jenis;
        el.setAttribute('role', jenis === 'error' ? 'alert' : 'status');
        el.dataset.kunci = jenis + '|' + pesan;
        el.style.setProperty('--toast-ms', DURASI + 'ms');

        var ikon = document.createElement('span');
        ikon.className = 'app-toast-ic';
        ikon.innerHTML = SVG[jenis];

        var isi = document.createElement('div');
        isi.className = 'app-toast-msg';
        isi.textContent = pesan;               // textContent: aman dari XSS

        var tutup = document.createElement('button');
        tutup.type = 'button';
        tutup.className = 'app-toast-x';
        tutup.setAttribute('aria-label', 'Tutup notifikasi');
        tutup.innerHTML = SVG_TUTUP;

        var bar = document.createElement('span');
        bar.className = 'app-toast-bar';
        bar.setAttribute('aria-hidden', 'true');

        el.appendChild(ikon); el.appendChild(isi); el.appendChild(tutup); el.appendChild(bar);
        return { el: el, tutup: tutup };
    }

    function lepas(el) {
        var i = tampilSekarang.indexOf(el);
        if (i > -1) { tampilSekarang.splice(i, 1); }
        if (el.parentNode) { el.parentNode.removeChild(el); }
        if (antrean.length) { var s = antrean.shift(); setTimeout(function () { jalankan(s.pesan, s.jenis); }, JEDA_ANTAR); }
    }

    function jalankan(pesan, jenis) {
        var b = buat(pesan, jenis), el = b.el;
        var sisa = DURASI, mulai = 0, timer = null, selesai = false;

        function tutup() {
            if (selesai) { return; }
            selesai = true;
            clearTimeout(timer);
            if (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) { lepas(el); return; }
            el.classList.add('is-leaving');
            el.addEventListener('animationend', function (e) { if (e.animationName.indexOf('-out') > -1) { lepas(el); } });
            setTimeout(function () { lepas(el); }, 600);   // pengaman bila animationend tidak terpicu
        }
        function jalan() { if (selesai) { return; } mulai = Date.now(); el.classList.remove('is-paused'); timer = setTimeout(tutup, sisa); }
        function jeda() { if (selesai) { return; } clearTimeout(timer); sisa = Math.max(300, sisa - (Date.now() - mulai)); el.classList.add('is-paused'); }

        el.addEventListener('mouseenter', jeda);
        el.addEventListener('mouseleave', jalan);
        el.addEventListener('focusin', jeda);
        el.addEventListener('focusout', jalan);
        b.tutup.addEventListener('click', tutup);

        tampilSekarang.push(el);
        region().appendChild(el);
        jalan();
    }

    function tampil(pesan, tag) {
        pesan = String(pesan == null ? '' : pesan).trim();
        if (!pesan) { return; }
        var jenis = normalJenis(tag);
        if (sudahAda(pesan, jenis)) { return; }        // hindari toast kembar
        if (tampilSekarang.length >= MAKS_TAMPIL) { antrean.push({ pesan: pesan, jenis: jenis }); return; }
        jalankan(pesan, jenis);
    }

    window.toast = {
        show: tampil,
        success: function (m) { tampil(m, 'success'); },
        error: function (m) { tampil(m, 'error'); },
        warning: function (m) { tampil(m, 'warning'); },
        info: function (m) { tampil(m, 'info'); },
        /* Untuk fetch/AJAX: tampilkan hasil respons JSON ({ok, error|detail|message}) sesuai kenyataan. */
        dariRespons: function (data, ok) {
            data = data || {};
            var pesan = data.message || data.detail || data.error || '';
            if (!pesan) { return; }
            tampil(pesan, ok === false || data.ok === false || data.error ? 'error' : 'success');
        }
    };

    function mulai() {
        // 1) Pesan dari Django Messages (hanya tampil sekali: server sudah menandainya terpakai)
        var sumber = document.getElementById('django-messages');
        var adaError = false;
        if (sumber) {
            Array.prototype.forEach.call(sumber.children, function (n, i) {
                var jenis = normalJenis(n.getAttribute('data-tag'));
                if (jenis === 'error') { adaError = true; }
                setTimeout(function () { tampil(n.textContent, jenis); }, i * JEDA_ANTAR);
            });
            sumber.parentNode.removeChild(sumber);
        }
        // 2) Form gagal validasi: error per kolom tetap tampil di form; toast hanya pengingat tambahan.
        if (!adaError && document.querySelector('form .errorlist li, form .field-error, form .invalid-feedback.d-block, form .is-invalid')) {
            tampil('Data belum valid. Periksa kolom yang ditandai.', 'error');
        }
    }

    if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', mulai); }
    else { mulai(); }
})();