"""Carga el catalogo de uniformes (hoy: San Francisco Javier) desde JSON.

Fuente de verdad: catalogo/data/uniformes_sfj.json (exportado del catalogo
real). Cada producto trae sus variantes por talla, con precio_override y
stock por talla, mas el nombre de archivo de su imagen (en
catalogo/data/uniformes_img/).

Crea/actualiza, idempotente, por nombre de producto (que es unico):
    Producto (familia Uniformes Escolares, colegio del JSON)
      .precio_base / .precio_costo / .descripcion / tiene_variantes=True
      imagen (desde catalogo/data/uniformes_img/, si falta)
      ProductoVariante por talla
        .precio_override (precio de esa talla)
        StockTienda(tienda online).cantidad = stock de la talla

Seguridad: DRY-RUN por defecto; --aplicar para escribir. Reproducible en
prod (las imagenes viajan en el repo).

Uso:
    python manage.py cargar_uniformes              # dry-run
    python manage.py cargar_uniformes --aplicar
    python manage.py cargar_uniformes --aplicar --archivo otra.json
"""
from __future__ import annotations

import json
import os
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.core.files import File
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from catalogo.models import (
    Atributo, Colegio, Familia, Producto, ProductoVariante, ValorAtributo,
)
from catalogo.sku import generar_sku_unico

DATA_FILE = Path(settings.BASE_DIR) / 'catalogo' / 'data' / 'uniformes_sfj.json'
IMG_DIR = Path(settings.BASE_DIR) / 'catalogo' / 'data' / 'uniformes_img'

# Orden de tallas: numericas antes que alfa, en orden natural.
_TALLA_ORDEN = {
    '4': 4, '6': 6, '8': 8, '10': 10, '12': 12, '14': 14, '16': 16,
    'XS': 50, 'S': 51, 'M': 52, 'L': 53, 'XL': 54, 'XXL': 55,
}


class Command(BaseCommand):
    help = 'Carga el catalogo de uniformes (SFJ) desde JSON. Idempotente.'

    def add_arguments(self, parser):
        parser.add_argument('--archivo', default=str(DATA_FILE))
        parser.add_argument(
            '--aplicar', action='store_true',
            help='Escribe los cambios. Sin esto es DRY-RUN.',
        )

    def handle(self, *args, **opts):
        archivo = Path(opts['archivo'])
        if not archivo.exists():
            raise CommandError(f'No existe: {archivo}')
        aplicar = opts['aplicar']
        if not aplicar:
            self.stdout.write(self.style.WARNING(
                'DRY-RUN: no se escribe nada. Usa --aplicar para confirmar.\n'))

        with archivo.open(encoding='utf-8') as f:
            catalogo = json.load(f)

        familia, _ = Familia.objects.get_or_create(nombre='Uniformes Escolares')
        atr_talla, _ = Atributo.objects.get_or_create(nombre='Talla')
        tienda = self._tienda_online()

        stats = {'creados': 0, 'actualizados': 0, 'sin_cambios': 0,
                 'variantes': 0, 'stock_set': 0, 'imagenes': 0}

        with transaction.atomic():
            for entry in catalogo:
                self._procesar(entry, familia, atr_talla, tienda, stats)
            if not aplicar:
                transaction.set_rollback(True)

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('=' * 50))
        verbo = '' if aplicar else '(DRY-RUN) '
        self.stdout.write(self.style.SUCCESS(
            f'{verbo}Productos: {len(catalogo)}\n'
            f'  Creados:       {stats["creados"]}\n'
            f'  Actualizados:  {stats["actualizados"]}\n'
            f'  Sin cambios:   {stats["sin_cambios"]}\n'
            f'  Variantes:     {stats["variantes"]}\n'
            f'  Stock seteado: {stats["stock_set"]}\n'
            f'  Imagenes:      {stats["imagenes"]}'
        ))
        self.stdout.write(self.style.SUCCESS('=' * 50))
        if not aplicar:
            self.stdout.write(self.style.WARNING(
                '\nDRY-RUN — corre con --aplicar para confirmar.'))

    def _tienda_online(self):
        from bodega.models import Tienda
        tid = getattr(settings, 'ECOMMERCE_TIENDA_ID', None)
        if tid:
            t = Tienda.objects.filter(pk=tid).first()
            if t:
                return t
        return Tienda.objects.filter(activa=True).first()

    def _procesar(self, entry, familia, atr_talla, tienda, stats):
        colegio = None
        if entry.get('colegio'):
            colegio, _ = Colegio.objects.get_or_create(nombre=entry['colegio'])

        meta = {
            'familia': familia,
            'colegio': colegio,
            'descripcion': entry.get('descripcion', ''),
            'precio_base': Decimal(str(entry.get('precio_base', 0))),
            'precio_costo': Decimal(str(entry.get('precio_costo', 0))),
            'tiene_variantes': True,
            'activo': True,
        }
        producto, creado = Producto.objects.get_or_create(
            nombre=entry['nombre'], defaults=meta)
        if creado:
            stats['creados'] += 1
            self.stdout.write(self.style.SUCCESS(f'  + {producto.nombre}'))
        else:
            cambios = [k for k, v in meta.items() if getattr(producto, k) != v]
            if cambios:
                for k, v in meta.items():
                    setattr(producto, k, v)
                producto.save()
                stats['actualizados'] += 1
                self.stdout.write(f'  ~ {producto.nombre}')
            else:
                stats['sin_cambios'] += 1

        # Imagen (si falta y hay archivo en el repo).
        if not producto.imagen and entry.get('imagen_file'):
            ruta = IMG_DIR / entry['imagen_file']
            if ruta.exists():
                with ruta.open('rb') as fh:
                    producto.imagen.save(entry['imagen_file'], File(fh), save=True)
                stats['imagenes'] += 1
            else:
                self.stdout.write(self.style.WARNING(
                    f'    img no encontrada: {ruta.name}'))

        # Variantes por talla.
        for v in entry.get('variantes', []):
            self._variante(producto, atr_talla, v, tienda, stats)

    def _variante(self, producto, atr_talla, vdata, tienda, stats):
        tallas = vdata.get('tallas') or []
        valores = []
        for t in tallas:
            val, _ = ValorAtributo.objects.get_or_create(
                atributo=atr_talla, valor=t,
                defaults={'orden': _TALLA_ORDEN.get(t, 99)})
            valores.append(val)
        valores_set = set(valores)

        variante = None
        for var in producto.variantes.all().prefetch_related('valores'):
            if set(var.valores.all()) == valores_set:
                variante = var
                break

        override = vdata.get('precio_override')
        override = Decimal(str(override)) if override is not None else None

        if variante is None:
            sku = generar_sku_unico(
                marca=producto.marca, nombre=producto.nombre,
                valores=[v.valor for v in valores])
            variante = ProductoVariante.objects.create(
                producto=producto, sku=sku,
                precio_override=override, activa=vdata.get('activa', True))
            variante.valores.set(valores_set)
            stats['variantes'] += 1
        else:
            if variante.precio_override != override or variante.activa != vdata.get('activa', True):
                variante.precio_override = override
                variante.activa = vdata.get('activa', True)
                variante.save(update_fields=['precio_override', 'activa'])

        # Stock por tienda.
        if tienda:
            from bodega.models import StockTienda
            cant = int(vdata.get('stock') or 0)
            st, _ = StockTienda.objects.get_or_create(
                tienda=tienda, variante=variante, defaults={'cantidad': cant})
            if st.cantidad != cant:
                st.cantidad = cant
                st.save(update_fields=['cantidad'])
            stats['stock_set'] += 1
