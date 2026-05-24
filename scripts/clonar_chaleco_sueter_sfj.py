"""Script one-off: clona Chaleco SFJ -> Sueter SFJ con todas sus variantes.

El sueter es abierto, el chaleco cerrado. Misma tela, mismo bordado,
mismas tallas, mismos precios. Solo difiere en el corte y las fotos.

Uso:
    python manage.py shell < scripts/clonar_chaleco_sueter_sfj.py

Idempotente: si Sueter SFJ ya existe, no lo duplica.
"""

from django.db import transaction

from catalogo.models import Producto, ProductoVariante
from catalogo.sku import generar_sku_unico


with transaction.atomic():
    chaleco = Producto.objects.get(nombre='Chaleco SFJ')

    sueter, created = Producto.objects.get_or_create(
        nombre='Sueter SFJ',
        defaults={
            'familia': chaleco.familia,
            'colegio': chaleco.colegio,
            'descripcion': (
                'Sueter abierto oficial del colegio San Francisco Javier. '
                'Misma tela y bordado que el chaleco cerrado, pero con '
                'apertura frontal y botones.'
            ),
            'precio_base': chaleco.precio_base,
            'precio_costo': chaleco.precio_costo,
            'tiene_variantes': True,
            'activo': True,
        },
    )

    if created:
        print(f'+ Producto creado: {sueter.nombre} (pk={sueter.pk})')
        for v_chal in chaleco.variantes.all():
            valores = list(v_chal.valores.all())
            sku = generar_sku_unico(
                marca=sueter.marca,
                nombre=sueter.nombre,
                valores=[va.valor for va in valores],
            )
            v_su = ProductoVariante.objects.create(
                producto=sueter, sku=sku,
                precio_override=v_chal.precio_override, activa=True,
            )
            v_su.valores.set(valores)
            print(f'  + variante {sku}: precio {v_chal.precio_override}')
    else:
        print(f'Sueter SFJ ya existia (pk={sueter.pk}) -- no se duplica.')

    # Clarificar la descripcion del Chaleco para diferenciar visualmente
    # en el catalogo.
    if not chaleco.descripcion:
        chaleco.descripcion = (
            'Chaleco cerrado oficial del colegio San Francisco Javier, '
            'sin apertura frontal.'
        )
        chaleco.save(update_fields=['descripcion'])
        print('~ Chaleco SFJ: descripcion agregada para diferenciar.')
    elif 'cerrado' not in chaleco.descripcion.lower():
        chaleco.descripcion = (
            chaleco.descripcion.rstrip('.') +
            ' (chaleco cerrado, sin apertura frontal).'
        )[:1000]
        chaleco.save(update_fields=['descripcion'])
        print('~ Chaleco SFJ: descripcion actualizada para diferenciar.')
    else:
        print('= Chaleco SFJ: descripcion ya menciona "cerrado", no se toca.')
