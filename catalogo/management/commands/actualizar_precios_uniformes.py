"""Actualiza precios de variantes de uniformes desde un CSV.

Diseñado para los uniformes escolares: cada fila del CSV es una talla, y
las columnas (a partir de la 2da) son nombres de Producto. Para cada
celda no vacia, se actualiza el `precio_override` de la variante
(Producto + Talla). Si la variante no existe pero el producto sí, se
crea con el SKU autogenerado.

Formato del CSV:

    Talla,Polera piqué SFJ,Chaleco SFJ,Buzo SFJ Completo,...
    4,12900,16900,21900,...
    6,13900,16900,22900,...
    S,18900,24900,34900,...
    XXL,21400,28400,39900,...

Uso:
    # Dry run: muestra cambios sin aplicar.
    python manage.py actualizar_precios_uniformes catalogo/data/precios_uniformes_sfj.csv

    # Aplicar.
    python manage.py actualizar_precios_uniformes catalogo/data/precios_uniformes_sfj.csv --aplicar

    # Crear variantes faltantes cuando una talla no existe en el producto.
    python manage.py actualizar_precios_uniformes <csv> --aplicar --crear-faltantes

Idempotente: re-correrlo no duplica nada. Si el precio del CSV coincide
con el override actual de la variante, no se toca.
"""

from __future__ import annotations

import csv
from decimal import Decimal
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from catalogo.models import Atributo, Producto, ProductoVariante, ValorAtributo
from catalogo.sku import generar_sku_unico


class Command(BaseCommand):
    help = 'Actualiza precios de variantes de uniformes desde un CSV (talla x producto).'

    def add_arguments(self, parser):
        parser.add_argument('csv_path', help='Ruta al CSV con la grilla de precios.')
        parser.add_argument(
            '--aplicar', action='store_true',
            help='Si se omite, solo lista lo que SERIA actualizado (dry-run).',
        )
        parser.add_argument(
            '--crear-faltantes', action='store_true',
            help='Crea variantes para las tallas que aparecen en el CSV '
                 'pero no existen en el producto. Sin esta flag, esas tallas '
                 'se reportan como warning.',
        )

    def handle(self, *args, **opts):
        csv_path = Path(opts['csv_path'])
        if not csv_path.exists():
            raise CommandError(f'CSV no encontrado: {csv_path}')

        aplicar = opts['aplicar']
        crear_faltantes = opts['crear_faltantes']

        if not aplicar:
            self.stdout.write(self.style.WARNING(
                'DRY-RUN: solo lista — usa --aplicar para escribir cambios.\n'
            ))

        atr_talla, _ = Atributo.objects.get_or_create(nombre='Talla')

        stats = {
            'actualizadas': 0, 'sin_cambios': 0, 'creadas': 0,
            'producto_no_existe': 0, 'variante_no_existe_skipped': 0,
        }

        with csv_path.open(encoding='utf-8-sig', newline='') as f:
            reader = csv.reader(f)
            header = next(reader)
            if header[0].strip().lower() != 'talla':
                raise CommandError(
                    f'Primera columna del CSV debe ser "Talla", encontre: {header[0]!r}',
                )
            producto_nombres = [c.strip() for c in header[1:]]

            self.stdout.write(self.style.NOTICE(
                f'Productos a actualizar: {", ".join(producto_nombres)}\n'
            ))

            with transaction.atomic():
                productos = {}
                for nombre in producto_nombres:
                    p = Producto.objects.filter(nombre=nombre).first()
                    if not p:
                        self.stdout.write(self.style.ERROR(
                            f'  ! Producto NO existe: {nombre!r} — columna ignorada.'
                        ))
                        stats['producto_no_existe'] += 1
                    productos[nombre] = p

                for row in reader:
                    if not row or not row[0].strip():
                        continue
                    talla = row[0].strip()
                    valor_talla, _ = ValorAtributo.objects.get_or_create(
                        atributo=atr_talla, valor=talla,
                        defaults={'orden': _orden_talla(talla)},
                    )
                    for nombre, precio_str in zip(producto_nombres, row[1:]):
                        producto = productos.get(nombre)
                        if not producto:
                            continue
                        precio_str = (precio_str or '').strip()
                        if not precio_str:
                            continue
                        try:
                            precio = Decimal(precio_str.replace('.', '').replace('$', ''))
                        except Exception:
                            self.stdout.write(self.style.WARNING(
                                f'  ? {nombre} {talla}: precio invalido {precio_str!r}, saltado.'
                            ))
                            continue
                        self._procesar_celda(
                            producto, valor_talla, talla, precio,
                            aplicar, crear_faltantes, stats,
                        )

                if not aplicar:
                    # Dry-run: rollback la transaccion explicito por seguridad.
                    transaction.set_rollback(True)

        self._reportar(stats, aplicar)

    def _procesar_celda(self, producto, valor_talla, talla, precio,
                        aplicar, crear_faltantes, stats):
        # Buscamos variante existente del producto con esa talla.
        variante = (
            producto.variantes
            .filter(valores=valor_talla)
            .first()
        )

        if variante:
            actual = variante.precio_override
            if actual == precio:
                stats['sin_cambios'] += 1
                return
            self.stdout.write(
                f'  ~ {producto.nombre} talla {talla}: '
                f'{actual or "—"} -> {precio}'
            )
            if aplicar:
                variante.precio_override = precio
                variante.save(update_fields=['precio_override'])
            stats['actualizadas'] += 1
            return

        # No existe variante con esa talla en el producto.
        if not crear_faltantes:
            self.stdout.write(self.style.WARNING(
                f'  ! {producto.nombre} talla {talla}: no existe, saltada '
                '(usa --crear-faltantes para crearla).'
            ))
            stats['variante_no_existe_skipped'] += 1
            return

        # Crear variante nueva.
        sku = generar_sku_unico(
            marca=producto.marca,
            nombre=producto.nombre,
            valores=[valor_talla.valor],
        )
        self.stdout.write(self.style.SUCCESS(
            f'  + {producto.nombre} talla {talla}: NUEVA variante SKU={sku} precio={precio}'
        ))
        if aplicar:
            v = ProductoVariante.objects.create(
                producto=producto, sku=sku,
                precio_override=precio, activa=True,
            )
            v.valores.set([valor_talla])
        stats['creadas'] += 1

    def _reportar(self, stats, aplicar):
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('-' * 50))
        verbo = '' if aplicar else 'SERIAN '
        self.stdout.write(self.style.SUCCESS(
            f'{verbo}Actualizadas:           {stats["actualizadas"]}\n'
            f'Sin cambios (ya estaba): {stats["sin_cambios"]}\n'
            f'{verbo}Creadas (nueva talla):  {stats["creadas"]}\n'
            f'Skipped (no crear):      {stats["variante_no_existe_skipped"]}\n'
            f'Productos no existen:    {stats["producto_no_existe"]}'
        ))
        self.stdout.write(self.style.SUCCESS('-' * 50))
        if not aplicar and (stats['actualizadas'] or stats['creadas']):
            self.stdout.write(self.style.WARNING(
                '\nPara aplicar:\n'
                '  python manage.py actualizar_precios_uniformes <csv> --aplicar'
                ' --crear-faltantes'
            ))


# Tallas numericas vienen antes que las alfa, y dentro de cada grupo en
# orden natural. Sirve para que el dropdown del PDP muestre tallas en
# orden razonable.
_TALLA_ORDEN = {
    '4': 4, '6': 6, '8': 8, '10': 10, '12': 12, '14': 14, '16': 16,
    'XS': 50, 'S': 51, 'M': 52, 'L': 53, 'XL': 54, 'XXL': 55,
}


def _orden_talla(talla: str) -> int:
    return _TALLA_ORDEN.get(talla, 99)
