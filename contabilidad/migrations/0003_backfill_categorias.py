"""Clasifica los MovimientoCaja existentes en categorías según el concepto.

- recibo_venta != null + tipo=ENTRADA → INGRESO_VENTA.
- concepto empieza con "Compra material:" → COSTO_INVENTARIO.
- concepto empieza con "Confección lote:" → COSTO_PRODUCCION.
- todo lo demás (tipo=SALIDA) → GASTO_OPERATIVO.

Idempotente: solo modifica los que están en OTRO (default tras la migración 0002).
"""
from django.db import migrations


def backfill(apps, schema_editor):
    Mov = apps.get_model('contabilidad', 'MovimientoCaja')
    qs = Mov.objects.filter(categoria='otro')
    for mov in qs.iterator():
        if mov.recibo_venta_id and mov.tipo == 'entrada':
            mov.categoria = 'ingreso_venta'
        elif mov.tipo == 'salida' and mov.concepto.startswith('Compra material:'):
            mov.categoria = 'costo_inventario'
        elif mov.tipo == 'salida' and mov.concepto.startswith('Confección lote:'):
            mov.categoria = 'costo_produccion'
        elif mov.tipo == 'salida':
            mov.categoria = 'gasto_operativo'
        else:
            continue
        mov.save(update_fields=['categoria'])


def reverse_(apps, schema_editor):
    pass  # No-op: dejamos las categorías clasificadas; revertir no aporta.


class Migration(migrations.Migration):
    dependencies = [
        ('contabilidad', '0002_auto_20260429_0941'),
    ]
    operations = [
        migrations.RunPython(backfill, reverse_code=reverse_),
    ]
