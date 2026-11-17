/*
 * Validasi langsung (saat mengetik) untuk form e-Prestasi.
 * Ini hanya BANTUAN tampilan: aturan resmi tetap dicek di server (validasi.py), jadi
 * form yang melewati skrip ini pun tetap ditolak server bila isinya tidak valid.
 *
 * Input ditandai lewat atribut data-validasi (diisi otomatis oleh form_fields.py):
 *   nama | angka (NIS/NIP) | email | hp | tahun-ajaran
 * Konfirmasi password dipasangkan otomatis: konfirmasi_password <-> password / password_baru.
 */
(function () {
  'use strict';

  var NOMOR_HP = /^(?:\+62|62|0)8[1-9][0-9]{7,10}$/;
  var EMAIL = /^[A-Za-z0-9](?:[A-Za-z0-9._%+\-]*[A-Za-z0-9])?@(?:[A-Za-z0-9](?:[A-Za-z0-9\-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,24}$/;

  var ATURAN = {
    nama: function (v) {
      if (/\d/.test(v)) return 'Nama tidak boleh mengandung angka.';
      if (!/^\p{L}[\p{L} .,'’\-]*$/u.test(v)) return "Nama hanya boleh berisi huruf, spasi, titik, koma, apostrof, dan tanda hubung (-).";
      return '';
    },
    angka: function (v, el) {
      var label = el.getAttribute('data-label') || 'Isian';
      var min = parseInt(el.getAttribute('data-min'), 10) || 0;
      var max = parseInt(el.getAttribute('data-max'), 10) || 0;
      if (!/^[0-9]+$/.test(v)) return label + ' hanya boleh berisi angka (tanpa huruf, spasi, atau karakter khusus).';
      if (min && v.length < min) return label + ' minimal ' + min + ' digit (sekarang ' + v.length + ').';
      if (max && v.length > max) return label + ' maksimal ' + max + ' digit (sekarang ' + v.length + ').';
      return '';
    },
    email: function (v) {
      if (/\s/.test(v)) return 'Email tidak boleh mengandung spasi.';
      if ((v.match(/@/g) || []).length !== 1) return "Email harus mengandung satu tanda '@'. Contoh: nama@gmail.com";
      if (v.indexOf('..') !== -1 || !EMAIL.test(v)) return 'Format email tidak valid. Contoh yang benar: nama@gmail.com';
      return '';
    },
    hp: function (v) {
      var nomor = v.replace(/[\s\-.()]/g, '');
      if (!/^\+?[0-9]+$/.test(nomor)) return 'Nomor telepon hanya boleh berisi angka (boleh diawali +).';
      if (!NOMOR_HP.test(nomor)) return 'Nomor telepon tidak valid. Contoh: 081234567890.';
      return '';
    },
    'tahun-ajaran': function (v) {
      var m = /^(\d{4})\s*\/\s*(\d{4})$/.exec(v);
      if (!m) return 'Format tahun ajaran harus YYYY/YYYY, contoh: 2025/2026.';
      if (parseInt(m[2], 10) !== parseInt(m[1], 10) + 1) return 'Tahun kedua harus tepat satu tahun setelah tahun pertama.';
      return '';
    }
  };

  function kotakPesan(el) {
    if (el._pesanLive) return el._pesanLive;
    var div = document.createElement('div');
    div.className = 'field-error live-error';
    div.setAttribute('role', 'alert');
    div.style.cssText = 'color:#c0392b;font-size:.78rem;margin-top:.25rem;';
    var jangkar = el.closest('.pw-field') || el;
    jangkar.insertAdjacentElement('afterend', div);
    el._pesanLive = div;
    return div;
  }

  function tampilkan(el, pesan) {
    var kotak = kotakPesan(el);
    kotak.textContent = pesan;
    kotak.style.display = pesan ? '' : 'none';
    el.classList.toggle('is-invalid', !!pesan);
    el.setAttribute('aria-invalid', pesan ? 'true' : 'false');
  }

  function periksa(el) {
    var nilai = el.value;
    if (el.type !== 'password') nilai = nilai.trim();
    if (!nilai) { tampilkan(el, ''); return; }   // kosong -> urusan "wajib diisi" di server
    var jenis = el.getAttribute('data-validasi');
    var aturan = ATURAN[jenis];
    tampilkan(el, aturan ? aturan(nilai, el) : '');
  }

  function pasangKonfirmasi(konf) {
    var induk = konf.form && (konf.form.querySelector('[name="password_baru"]') || konf.form.querySelector('[name="password"]'));
    if (!induk) return;
    function cek() {
      if (!konf.value) { tampilkan(konf, ''); return; }
      tampilkan(konf, konf.value !== induk.value ? 'Konfirmasi password tidak cocok dengan password.' : '');
    }
    konf.addEventListener('input', cek);
    induk.addEventListener('input', function () { if (konf.value) cek(); });
  }

  function pasangPanjangPassword(el) {
    var min = parseInt(el.getAttribute('data-min-password') || '8', 10);
    el.addEventListener('input', function () {
      if (!el.value) { tampilkan(el, ''); return; }
      tampilkan(el, el.value.length < min ? 'Password minimal ' + min + ' karakter (sekarang ' + el.value.length + ').' : '');
    });
  }

  function init() {
    document.querySelectorAll('input[data-validasi], textarea[data-validasi]').forEach(function (el) {
      el.addEventListener('input', function () { periksa(el); });
      el.addEventListener('blur', function () { periksa(el); });
      if (el.value) periksa(el);
    });
    document.querySelectorAll('input[name="konfirmasi_password"], input[name="konfirmasi"]').forEach(pasangKonfirmasi);
    // Password baru (bukan "password lama"/login): tampilkan panjang minimal langsung.
    document.querySelectorAll('input[name="password_baru"], form input[type="password"][name="password"][autocomplete="new-password"]').forEach(pasangPanjangPassword);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();
