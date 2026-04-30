"""Pobla `nombre_buscable` y `descripcion_buscable` para los registros
existentes con la versión normalizada (lowercase + sin acentos).

Idempotente — solo toca filas con buscable vacío.
"""
from django.db import migrations


def normalize(s: str) -> str:
    import unicodedata
    if not s:
        return ''
    nfkd = unicodedata.normalize('NFKD', str(s))
    sin_acentos = ''.join(c for c in nfkd if not unicodedata.combining(c))
    return sin_acentos.lower().strip()


def backfill(apps, schema_editor):
    Familia = apps.get_model('catalogo', 'Familia')
    Colegio = apps.get_model('catalogo', 'Colegio')
    Producto = apps.get_model('catalogo', 'Producto')

    for f in Familia.objects.all():
        f.nombre_buscable = normalize(f.nombre)
        f.save(update_fields=['nombre_buscable'])
    for c in Colegio.objects.all():
        c.nombre_buscable = normalize(c.nombre)
        c.save(update_fields=['nombre_buscable'])
    for p in Producto.objects.all():
        p.nombre_buscable = normalize(p.nombre)
        p.descripcion_buscable = normalize(p.descripcion)
        p.save(update_fields=['nombre_buscable', 'descripcion_buscable'])


def reverse_(apps, schema_editor):
    pass  # No-op


class Migration(migrations.Migration):
    dependencies = [
        ('catalogo', '0003_auto_20260429_1625'),
    ]
    operations = [
        migrations.RunPython(backfill, reverse_code=reverse_),
    ]
