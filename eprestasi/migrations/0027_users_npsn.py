from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('eprestasi', '0026_loginattempt'),
    ]

    operations = [
        # default='20219175' sekaligus mengisi NPSN SMKN 11 Bandung ke semua akun yang sudah ada.
        migrations.AddField(
            model_name='users',
            name='npsn',
            field=models.CharField(default='20219175', max_length=8),
        ),
    ]
