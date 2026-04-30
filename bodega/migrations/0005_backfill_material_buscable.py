"""Pobla `nombre_buscable` para Material existente."""
from django.db import migrations


def normalize(s: str) -> str:
    import unicodedata
    if not s:
        return ''
    nfkd = unicodedata.normalize('NFKD', str(s))
    sin_acentos = ''.join(c for c in nfkd if not unicodedata.combining(c))
    return sin_acentos.lower().strip()


def backfill(apps, schema_editor):
    Material = apps.get_model('bodega', 'Material')
    for m in Material.objects.all():
        m.nombre_buscable = normalize(m.nombre)
        m.save(update_fields=['nombre_buscable'])


def reverse_(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ('bodega', '0004_material_nombre_buscable'),
    ]
    operations = [
        migrations.RunPython(backfill, reverse_code=reverse_),
    ]
