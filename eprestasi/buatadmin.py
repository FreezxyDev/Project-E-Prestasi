from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth.hashers import make_password

from eprestasi.models import Users


class Command(BaseCommand):
    """
    Cara pakai (dijalankan di terminal, bukan di web):

        python manage.py buat_admin nama_admin passwordnya            -> buat admin biasa
        python manage.py buat_admin nama_super passwordnya --super    -> buat SUPER admin

    Super admin sengaja HANYA bisa dibuat lewat terminal ini (tidak ada tombol
    "buat super admin" di web sama sekali), supaya akun dengan hak tertinggi
    tidak mungkin dibuat oleh siapa pun yang cuma berhasil login sebagai admin biasa.

    Setelah ada 1 super admin, admin-admin berikutnya bisa dibuat lewat web
    di menu "Kelola Admin" (hanya muncul untuk super admin).
    """
    help = 'Membuat akun admin baru: python manage.py buat_admin <username> <password> [--super]'

    def add_arguments(self, parser):
        parser.add_argument('username', type=str)
        parser.add_argument('password', type=str)
        parser.add_argument(
            '--super',
            action='store_true',
            help='Jadikan akun ini super admin (bisa mengelola akun admin lain).'
        )

    def handle(self, *args, **options):
        username = options['username']
        password = options['password']
        role = 'super_admin' if options['super'] else 'admin'

        if Users.objects.filter(username=username).exists():
            raise CommandError(f'Username "{username}" sudah dipakai.')

        Users.objects.create(
            username=username,
            password=make_password(password),
            role=role,
        )
        label = 'Super admin' if role == 'super_admin' else 'Admin'
        self.stdout.write(self.style.SUCCESS(f'{label} "{username}" berhasil dibuat.'))