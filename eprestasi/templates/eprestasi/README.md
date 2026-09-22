# Update: Admin Dashboard - Konten Putih + Tombol New Kontekstual

## File yang berubah
- eprestasi/templates/eprestasi/base.html
- eprestasi/templates/eprestasi/dashboard.html

## Apa yang berubah
1. Tombol notifikasi (lonceng) di topnav dihapus.
2. Area konten (kanan sidebar) sekarang putih lembut (#f3f6f4), tidak
   menyilaukan -- sidebar & topnav tetap gelap ala terminal seperti
   sebelumnya. Semua card, tabel, teks di dashboard.html otomatis
   menyesuaikan (sudah di-adjust supaya tetap kebaca, sebelumnya teks putih
   yang sekarang jadi teks gelap).
3. Tombol "+ New" di topnav sekarang kontekstual:
   - Saat berada di menu Kelola User tab Siswa -> mengarah ke Tambah Siswa
   - Saat berada di menu Kelola User tab Kesiswaan -> mengarah ke Tambah Kesiswaan
   - Di halaman lain (dashboard, tahun ajaran, dst) -> default ke Tambah Siswa

## Cara pakai
Timpa 2 file di atas ke lokasi yang sama di project Anda, lalu refresh
browser (tidak perlu migrate, tidak ada perubahan model/database).
