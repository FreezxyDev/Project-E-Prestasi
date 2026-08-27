from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import Tahun_ajaran, Siswa

# Trigger 1: Otomatis Naik Kelas & Mengubah Status Alumni saat Tambah Tahun Ajaran Baru
@receiver(post_save, sender=Tahun_ajaran)
def auto_promosi_siswa(sender, instance, created, **kwargs):
    if created and instance.status == 'aktif':
        # Nonaktifkan semua tahun ajaran lama
        Tahun_ajaran.objects.exclude(id=instance.id).update(status='nonaktif')
        
        # Ambil siswa aktif dan naikkan tingkatnya
        siswa_aktif = Siswa.objects.filter(status='aktif')
        for siswa in siswa_aktif:
            siswa.tingkat += 1
            
            # Jika tingkat mencapai 13 (asumsi lulus kelas 12), ubah status menjadi alumni
            if siswa.tingkat >= 13:
                siswa.status = 'alumni'
                
            siswa.save()

# Trigger 2: Otomatis Generate QR Code saat Siswa Pertama Kali Dibuat
@receiver(post_save, sender=Siswa)
def auto_generate_qr_code(sender, instance, created, **kwargs):
    if created and not instance.qr_code:
        instance.generate_qr_code()
        instance.save()