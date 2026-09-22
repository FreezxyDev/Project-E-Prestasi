# Update: Import Siswa bisa isi Nama, Kelas, Jurusan sekaligus

## File yang berubah
- eprestasi/import_views.py
- eprestasi/templates/eprestasi/siswa/import.html
- eprestasi/templates/eprestasi/siswa/import_hasil.html
- eprestasi/templates/eprestasi/base.html (nambahin kembali style .topbar
  yang ternyata sempat hilang saat redesign dashboard admin -- dipakai oleh
  banyak halaman admin lain seperti halaman ini, jadi sekalian dibenerin)

## Apa yang berubah
Sebelumnya file Excel import siswa cuma menerima kolom NIS + Password.
Sekarang ditambah 3 kolom opsional: **Nama, Kelas, Jurusan**.

- Kalau diisi di Excel, data itu LANGSUNG tersimpan ke akun siswa saat
  akun dibuat -- jadi begitu siswa pertama kali login dan buka halaman
  "Lengkapi Profil", field Nama/Kelas/Jurusan SUDAH otomatis terisi.
  Siswa tinggal melengkapi sisanya (email & no HP) yang memang cuma bisa
  diisi sendiri oleh siswa.
- Kelas & Jurusan divalidasi terhadap pilihan resmi di sistem (tidak peduli
  huruf besar/kecil atau spasi berlebih). Kalau nilainya tidak dikenali
  (typo dsb), akun TETAP dibuat, cuma kolom itu dikosongkan dan dicatat
  di kolom "Catatan" pada halaman hasil import -- tidak menggagalkan
  keseluruhan baris.
- Template Excel yang bisa didownload (tombol "Download template Excel")
  sekarang punya sheet kedua "Pilihan Kelas & Jurusan" berisi daftar nilai
  resmi yang bisa langsung di-copy-paste, supaya tidak salah ketik.
- Halaman hasil import sekarang menampilkan kolom Nama/Kelas/Jurusan/Catatan
  juga, bukan cuma NIS/Username/Password.

## Cara pakai
Timpa 4 file di atas ke lokasi yang sama di project Anda, lalu refresh
browser (tidak ada perubahan model/database, tidak perlu migrate).
