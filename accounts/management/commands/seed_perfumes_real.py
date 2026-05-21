"""Carga el catalogo real de perfumes desde JSON.

Lee `catalogo/data/perfumes_reales.json` (fuente de verdad versionada)
y crea/actualiza productos en la base. Idempotente: corrérselo varias
veces no duplica nada.

Uso:
    python manage.py seed_perfumes_real
    python manage.py seed_perfumes_real --solo-mujer
    python manage.py seed_perfumes_real --solo-hombre
    python manage.py seed_perfumes_real --solo-unisex
    python manage.py seed_perfumes_real --update-precios   # rescribe precios aunque ya exista
    python manage.py seed_perfumes_real --con-stock         # crea StockTienda en la tienda activa
    python manage.py seed_perfumes_real --stock=5           # con cantidad custom

El JSON es la fuente de verdad. Si necesitas corregir un perfume
(precio, nota, etc.), editas el JSON y re-corres el comando con
`--update-precios`.

Las imagenes NO se cargan aca — la duena las sube despues via
`/admin/catalogo/producto/<pk>/change/`.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import transaction

from catalogo.models import Familia, Producto


DATA_FILE = Path(__file__).resolve().parents[3] / 'catalogo' / 'data' / 'perfumes_reales.json'


class Command(BaseCommand):
    help = 'Carga el catalogo real de perfumes desde catalogo/data/perfumes_reales.json.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--solo-mujer', action='store_true',
            help='Solo carga perfumes con genero=mujer.',
        )
        parser.add_argument(
            '--solo-hombre', action='store_true',
            help='Solo carga perfumes con genero=hombre.',
        )
        parser.add_argument(
            '--solo-unisex', action='store_true',
            help='Solo carga perfumes con genero=unisex.',
        )
        parser.add_argument(
            '--update-precios', action='store_true',
            help='Si el producto ya existe, sobrescribe precio_base con el del JSON.',
        )
        parser.add_argument(
            '--con-stock', action='store_true',
            help='Crea StockTienda en la primera tienda activa.',
        )
        parser.add_argument(
            '--stock', type=int, default=10,
            help='Cantidad de stock inicial por SKU (default 10). Requiere --con-stock.',
        )
        parser.add_argument(
            '--purgar-no-en-json', action='store_true',
            help=('Marca como activo=False los perfumes que estan en la DB pero NO en '
                  'el JSON (leftovers de seeds viejos). NO borra — solo desactiva. '
                  'Para borrar de verdad: usar el admin Django.'),
        )

    def handle(self, *args, **opts):
        if not DATA_FILE.exists():
            self.stderr.write(self.style.ERROR(
                f'No se encuentra el archivo de datos: {DATA_FILE}\n'
                'Verifica que catalogo/data/perfumes_reales.json este en el repo.'
            ))
            return

        with DATA_FILE.open(encoding='utf-8') as f:
            data = json.load(f)

        perfumes = data.get('perfumes', [])
        meta = data.get('_meta', {})
        self.stdout.write(self.style.NOTICE(
            f'Cargando {meta.get("total_skus", len(perfumes))} SKUs (version {meta.get("version", "?")})'
        ))

        # Filtros de genero (mutuamente excluyentes).
        if opts['solo_mujer']:
            perfumes = [p for p in perfumes if p.get('genero') == 'mujer']
            self.stdout.write('Filtro: solo mujer')
        elif opts['solo_hombre']:
            perfumes = [p for p in perfumes if p.get('genero') == 'hombre']
            self.stdout.write('Filtro: solo hombre')
        elif opts['solo_unisex']:
            perfumes = [p for p in perfumes if p.get('genero') == 'unisex']
            self.stdout.write('Filtro: solo unisex')

        familia_perfumes = self._get_familia_perfumes()

        stats = {'creados': 0, 'actualizados': 0, 'sin_cambios': 0,
                 'con_stock': 0, 'desactivados': 0}
        update_precios = opts['update_precios']
        con_stock = opts['con_stock']
        cantidad_stock = opts['stock']

        tienda = None
        if con_stock:
            tienda = self._get_tienda_default()
            if not tienda:
                self.stderr.write(self.style.WARNING(
                    'No hay tienda activa — saltando creacion de stock. '
                    'Crea una en /admin/bodega/tienda/ y reintenta.'
                ))
                con_stock = False

        with transaction.atomic():
            for entry in perfumes:
                self._procesar(entry, familia_perfumes, update_precios,
                               con_stock, tienda, cantidad_stock, stats)

            if opts['purgar_no_en_json']:
                nombres_json = {p['nombre'] for p in perfumes}
                qs = Producto.objects.filter(
                    familia=familia_perfumes, activo=True,
                ).exclude(nombre__in=nombres_json)
                stats['desactivados'] = qs.count()
                for p in qs:
                    self.stdout.write(self.style.WARNING(f'  desactivado: {p.nombre}'))
                qs.update(activo=False)

        self._reportar(stats, len(perfumes))

    # ─── Helpers ─────────────────────────────────────────────────────

    def _get_familia_perfumes(self):
        fam, created = Familia.objects.get_or_create(nombre='Perfumes')
        if created:
            self.stdout.write(self.style.SUCCESS('Familia "Perfumes" creada.'))
        return fam

    def _get_tienda_default(self):
        """Primera tienda activa — donde dejar el stock inicial."""
        from bodega.models import Tienda
        # Si despues necesitamos diferenciar entre tienda fisica y ecommerce,
        # podemos agregar un campo es_ecommerce a Tienda. Por ahora, cualquier
        # tienda activa.
        return Tienda.objects.filter(activa=True).first()

    def _procesar(self, entry, familia, update_precios, con_stock, tienda,
                  cantidad_stock, stats):
        nombre = entry['nombre']
        defaults = {
            'familia': familia,
            'descripcion': entry.get('descripcion', ''),
            'precio_base': Decimal(str(entry.get('precio_base', 0))),
            'marca': entry.get('marca', ''),
            'concentracion': entry.get('concentracion', ''),
            'medida_ml': entry.get('medida_ml'),
            'familia_olfativa': entry.get('familia_olfativa', ''),
            'notas_clave': entry.get('notas_clave', ''),
            'genero': entry.get('genero', ''),
            'tiene_variantes': False,
            'activo': True,
        }

        producto, creado = Producto.objects.get_or_create(
            nombre=nombre, defaults=defaults,
        )

        if creado:
            stats['creados'] += 1
            self.stdout.write(f'  + {nombre}')
        else:
            # Actualiza siempre los campos metadata de perfume (idempotente y
            # util si cambia la fuente). Precio solo si pasaron --update-precios.
            actualizar = {
                'descripcion': defaults['descripcion'],
                'marca': defaults['marca'],
                'concentracion': defaults['concentracion'],
                'medida_ml': defaults['medida_ml'],
                'familia_olfativa': defaults['familia_olfativa'],
                'notas_clave': defaults['notas_clave'],
                'genero': defaults['genero'],
            }
            if update_precios:
                actualizar['precio_base'] = defaults['precio_base']

            cambios = False
            for campo, nuevo in actualizar.items():
                if getattr(producto, campo) != nuevo:
                    setattr(producto, campo, nuevo)
                    cambios = True
            if cambios:
                producto.save()
                stats['actualizados'] += 1
                self.stdout.write(f'  ~ {nombre}')
            else:
                stats['sin_cambios'] += 1

        # Stock en la tienda activa (idempotente — solo crea si falta).
        if con_stock and tienda:
            from bodega.models import StockTienda
            _, stock_creado = StockTienda.objects.get_or_create(
                tienda=tienda, producto=producto,
                defaults={'cantidad': cantidad_stock},
            )
            if stock_creado:
                stats['con_stock'] += 1

    def _reportar(self, stats, total):
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('-' * 50))
        self.stdout.write(self.style.SUCCESS(
            f'Procesados: {total}\n'
            f'  Creados:       {stats["creados"]}\n'
            f'  Actualizados:  {stats["actualizados"]}\n'
            f'  Sin cambios:   {stats["sin_cambios"]}\n'
            f'  Stock creado:  {stats["con_stock"]}\n'
            f'  Desactivados:  {stats["desactivados"]} (leftovers no presentes en JSON)'
        ))
        self.stdout.write(self.style.SUCCESS('-' * 50))
        if stats['creados'] == 0 and stats['actualizados'] == 0:
            self.stdout.write('Nada que hacer — todos los productos ya estan al dia.')
        else:
            self.stdout.write(self.style.NOTICE(
                'Recorda subir las imagenes despues via:\n'
                '    /admin/catalogo/producto/<pk>/change/'
            ))
