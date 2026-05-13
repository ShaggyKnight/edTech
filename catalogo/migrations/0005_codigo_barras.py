from django.db import migrations, models


def backfill_codigos_internos(apps, schema_editor):
    """Para items existentes (productos sin variantes y variantes activas)
    genera el EAN-13 interno con prefijo 200. Los productos comerciales
    que ya tengan codigo asignado externamente se deben editar despues
    desde el backoffice (este backfill solo llena lo vacio)."""
    from catalogo.barcode import generar_codigo_interno
    Producto = apps.get_model('catalogo', 'Producto')
    ProductoVariante = apps.get_model('catalogo', 'ProductoVariante')

    # Productos sin variantes: codigo vive a nivel de producto.
    for p in Producto.objects.filter(tiene_variantes=False, codigo_barras__isnull=True):
        p.codigo_barras = generar_codigo_interno('p', p.pk)
        p.save(update_fields=['codigo_barras'])

    # Variantes (de productos con variantes): codigo vive a nivel de variante.
    for v in ProductoVariante.objects.filter(codigo_barras__isnull=True):
        v.codigo_barras = generar_codigo_interno('v', v.pk)
        v.save(update_fields=['codigo_barras'])


def deshacer_backfill(apps, schema_editor):
    """Si se hace migrate al estado anterior, los campos se borran al
    revertir el AddField. El RunPython queda no-op (no podemos volver
    a llenarlos porque la columna ya no existe)."""
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('catalogo', '0004_backfill_buscable'),
    ]

    operations = [
        migrations.AddField(
            model_name='producto',
            name='codigo_barras',
            field=models.CharField(blank=True, help_text='EAN-13 / Code128. Si el producto tiene variantes el código vive a nivel de variante; este campo solo se usa para productos sin variantes (ej. perfumes).', max_length=32, null=True, unique=True),
        ),
        migrations.AddField(
            model_name='productovariante',
            name='codigo_barras',
            field=models.CharField(blank=True, help_text='EAN-13 / Code128. Para uniformes confeccionados se genera automáticamente con prefijo 200 (rango GS1 reservado a uso interno) — ver catalogo.barcode.generar_codigo_interno.', max_length=32, null=True, unique=True),
        ),
        migrations.RunPython(backfill_codigos_internos, deshacer_backfill),
    ]
