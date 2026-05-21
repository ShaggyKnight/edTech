"""Carga el catalogo real de perfumes desde JSON.

Lee `catalogo/data/perfumes_reales.json` y crea/actualiza productos
con UNA variante por entrada (combinacion volumen + concentracion).

Modelo:
    Producto                      = el perfume (ej. "Yara")
      .marca = "Lattafa"
      .familia_olfativa = "Oriental Gourmand"
      .genero = "mujer"
      .tiene_variantes = True
      ProductoVariante              = la presentacion comprable
        .sku = "LATTAFA-YARA-100ML-EDP"
        .valores = [Volumen=100 ml, Concentracion=EDP]
        StockTienda.variante       = stock por tienda

Esto permite agregar mas tarde sin tocar codigo:
    Producto "Yara" + ProductoVariante 50ml EDT (precio distinto)

Idempotente: corrérselo varias veces no duplica nada. Reusa atributos
y valores existentes via get_or_create.

Uso:
    python manage.py seed_perfumes_real
    python manage.py seed_perfumes_real --solo-mujer | --solo-hombre | --solo-unisex
    python manage.py seed_perfumes_real --update-precios
    python manage.py seed_perfumes_real --con-stock --stock=10
    python manage.py seed_perfumes_real --purgar-no-en-json
    python manage.py seed_perfumes_real --reset
        ELIMINA los perfumes existentes (productos + variantes + stock) y
        carga limpio desde el JSON. Solo en dev: en prod usar el flujo
        --purgar-no-en-json que desactiva sin borrar.

Imagenes no se cargan aca — subida posterior via admin.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import transaction

from catalogo.models import (
    Atributo, Familia, Producto, ProductoVariante, ValorAtributo,
)
from catalogo.sku import generar_sku_unico


DATA_FILE = Path(__file__).resolve().parents[3] / 'catalogo' / 'data' / 'perfumes_reales.json'

# Display de las concentraciones para que el chip del PDP las muestre bonito.
CONC_DISPLAY = {
    'EDP': 'EDP',
    'EDT': 'EDT',
    'EDC': 'EDC',
    'BODY': 'Body Spray',
    'SET': 'Set',
}


class Command(BaseCommand):
    help = 'Carga el catalogo real de perfumes desde catalogo/data/perfumes_reales.json.'

    def add_arguments(self, parser):
        parser.add_argument('--solo-mujer', action='store_true')
        parser.add_argument('--solo-hombre', action='store_true')
        parser.add_argument('--solo-unisex', action='store_true')
        parser.add_argument(
            '--update-precios', action='store_true',
            help='Sobrescribe precios desde el JSON aunque el producto ya exista.',
        )
        parser.add_argument(
            '--con-stock', action='store_true',
            help='Crea StockTienda en la tienda activa.',
        )
        parser.add_argument(
            '--stock', type=int, default=10,
            help='Cantidad de stock inicial por variante (default 10).',
        )
        parser.add_argument(
            '--purgar-no-en-json', action='store_true',
            help='Desactiva (activo=False) los perfumes en DB no listados en el JSON.',
        )
        parser.add_argument(
            '--reset', action='store_true',
            help='DESTRUCTIVO: elimina productos/variantes/stock de TODOS los '
                 'perfumes existentes antes de seedear. Solo dev.',
        )

    def handle(self, *args, **opts):
        if not DATA_FILE.exists():
            self.stderr.write(self.style.ERROR(f'Falta {DATA_FILE}'))
            return

        with DATA_FILE.open(encoding='utf-8') as f:
            data = json.load(f)
        perfumes = data.get('perfumes', [])
        meta = data.get('_meta', {})
        self.stdout.write(self.style.NOTICE(
            f'Cargando {meta.get("total_skus", len(perfumes))} SKUs '
            f'(version {meta.get("version", "?")})'
        ))

        # Filtros de genero
        if opts['solo_mujer']:
            perfumes = [p for p in perfumes if p.get('genero') == 'mujer']
        elif opts['solo_hombre']:
            perfumes = [p for p in perfumes if p.get('genero') == 'hombre']
        elif opts['solo_unisex']:
            perfumes = [p for p in perfumes if p.get('genero') == 'unisex']

        familia_perfumes = self._get_familia()
        atr_volumen, atr_conc = self._get_atributos()

        tienda = None
        if opts['con_stock']:
            tienda = self._get_tienda()
            if not tienda:
                self.stderr.write(self.style.WARNING(
                    'No hay tienda activa — saltando creacion de stock.'
                ))
                opts['con_stock'] = False

        stats = {'creados': 0, 'actualizados': 0, 'sin_cambios': 0,
                 'con_stock': 0, 'desactivados': 0, 'eliminados': 0}

        with transaction.atomic():
            if opts['reset']:
                stats['eliminados'] = self._reset(familia_perfumes)

            for entry in perfumes:
                self._procesar(
                    entry, familia_perfumes, atr_volumen, atr_conc,
                    opts['update_precios'], opts['con_stock'], tienda,
                    opts['stock'], stats,
                )

            if opts['purgar_no_en_json']:
                stats['desactivados'] = self._purgar(perfumes, familia_perfumes)

        self._reportar(stats, len(perfumes))

    # ─── Helpers de setup ────────────────────────────────────────────

    def _get_familia(self):
        fam, created = Familia.objects.get_or_create(nombre='Perfumes')
        if created:
            self.stdout.write(self.style.SUCCESS('Familia "Perfumes" creada.'))
        return fam

    def _get_atributos(self):
        """Atributo 'Volumen' y 'Concentracion' que se usaran en todas las
        variantes de perfumes. Si no existen, se crean."""
        vol, _ = Atributo.objects.get_or_create(nombre='Volumen')
        conc, _ = Atributo.objects.get_or_create(nombre='Concentracion')
        return vol, conc

    def _get_tienda(self):
        from bodega.models import Tienda
        return Tienda.objects.filter(activa=True).first()

    # ─── Procesamiento de cada perfume ──────────────────────────────

    def _procesar(self, entry, familia, atr_vol, atr_conc,
                  update_precios, con_stock, tienda, cantidad_stock, stats):
        nombre = entry['nombre']
        precio_base = Decimal(str(entry.get('precio_base', 0)))
        precio_oferta = entry.get('precio_oferta_online')
        precio_oferta = Decimal(str(precio_oferta)) if precio_oferta else None

        # 1. Producto (concepto del perfume)
        defaults_producto = {
            'familia': familia,
            'descripcion': entry.get('descripcion', ''),
            'precio_base': precio_base,
            'marca': entry.get('marca', ''),
            # Mantenemos los campos a nivel producto tambien (denormalizacion
            # util para queries simples y display del PDP por defecto).
            'concentracion': entry.get('concentracion', ''),
            'medida_ml': entry.get('medida_ml'),
            'familia_olfativa': entry.get('familia_olfativa', ''),
            'notas_clave': entry.get('notas_clave', ''),
            'genero': entry.get('genero', ''),
            'tiene_variantes': True,  # CAMBIO: ahora con variantes
            'activo': True,
        }

        producto, creado = Producto.objects.get_or_create(
            nombre=nombre, defaults=defaults_producto,
        )

        if creado:
            stats['creados'] += 1
            self.stdout.write(f'  + {nombre}')
        else:
            actualizar = dict(defaults_producto)
            actualizar.pop('precio_base', None)  # solo si --update-precios
            if update_precios:
                actualizar['precio_base'] = precio_base
            cambios = False
            for k, v in actualizar.items():
                if getattr(producto, k) != v:
                    setattr(producto, k, v)
                    cambios = True
            if cambios:
                producto.save()
                stats['actualizados'] += 1
                self.stdout.write(f'  ~ {nombre}')
            else:
                stats['sin_cambios'] += 1

        # 2. Valores de atributo (idempotente)
        val_vol = self._ensure_valor_volumen(atr_vol, entry.get('medida_ml'))
        val_conc = self._ensure_valor_concentracion(atr_conc, entry.get('concentracion'))

        # 3. Variante (1 por perfume — la combinacion volumen + concentracion)
        # Buscamos por producto y conjunto de valores. Si ya existe, no
        # duplicamos. Como la unicidad del SKU choca si hay 2 perfumes con
        # mismo marca+nombre+valores, usamos la primera variante del producto
        # con esos mismos valores como match.
        variante = self._get_or_create_variante(
            producto, val_vol, val_conc, precio_oferta,
        )

        # 4. Stock por tienda
        if con_stock and tienda:
            from bodega.models import StockTienda
            _, stock_creado = StockTienda.objects.get_or_create(
                tienda=tienda, variante=variante,
                defaults={'cantidad': cantidad_stock},
            )
            if stock_creado:
                stats['con_stock'] += 1

    def _ensure_valor_volumen(self, atributo, medida_ml):
        if not medida_ml:
            return None
        valor_str = f'{medida_ml} ml'
        val, _ = ValorAtributo.objects.get_or_create(
            atributo=atributo, valor=valor_str,
            defaults={'orden': medida_ml},  # orden = ml para sort ascendente
        )
        return val

    def _ensure_valor_concentracion(self, atributo, codigo):
        if not codigo:
            return None
        display = CONC_DISPLAY.get(codigo, codigo)
        val, _ = ValorAtributo.objects.get_or_create(
            atributo=atributo, valor=display,
        )
        return val

    def _get_or_create_variante(self, producto, val_vol, val_conc, precio_oferta):
        """Devuelve la variante (volumen, concentracion) del producto, creando
        si no existe. SKU se autogenera via generar_sku_unico.

        Orden de valores en el SKU: Volumen primero, Concentracion despues
        (ej. LATTAFA-YARA-100ML-EDP), para que el SKU sea deterministico
        independiente del orden de inserccion en la M2M.
        """
        valores_ordenados = [v for v in (val_vol, val_conc) if v]
        valores_set = set(valores_ordenados)

        # Buscar variante existente con el MISMO set de valores
        for v in producto.variantes.all().prefetch_related('valores'):
            if set(v.valores.all()) == valores_set:
                # Actualizar precio override si cambio
                if precio_oferta is not None and v.precio_override != precio_oferta:
                    v.precio_override = precio_oferta
                    v.save(update_fields=['precio_override'])
                return v

        # No existe — crear
        sku = generar_sku_unico(
            marca=producto.marca,
            nombre=producto.nombre,
            valores=[v.valor for v in valores_ordenados],
        )
        variante = ProductoVariante.objects.create(
            producto=producto, sku=sku,
            precio_override=precio_oferta, activa=True,
        )
        variante.valores.set(valores_set)
        return variante

    # ─── Operaciones administrativas ────────────────────────────────

    def _reset(self, familia):
        """Elimina TODOS los perfumes (productos + variantes + stock).
        Cuidado: solo dev. Los recibos viejos que referenciaban estas
        variantes mantienen su detalle (FK on_delete=SET_NULL si esta
        configurado) o fallan (PROTECT)."""
        from bodega.models import StockTienda
        qs = Producto.objects.filter(familia=familia)
        n = qs.count()
        StockTienda.objects.filter(
            variante__producto__in=qs,
        ).delete()
        ProductoVariante.objects.filter(producto__in=qs).delete()
        qs.delete()
        self.stdout.write(self.style.WARNING(
            f'RESET: {n} producto(s) de "Perfumes" eliminados.'
        ))
        return n

    def _purgar(self, perfumes_json, familia):
        """Desactiva (activo=False) productos que no estan en el JSON."""
        nombres = {p['nombre'] for p in perfumes_json}
        qs = Producto.objects.filter(
            familia=familia, activo=True,
        ).exclude(nombre__in=nombres)
        n = qs.count()
        for p in qs:
            self.stdout.write(self.style.WARNING(f'  desactivado: {p.nombre}'))
        qs.update(activo=False)
        return n

    def _reportar(self, stats, total):
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('-' * 50))
        if stats.get('eliminados'):
            self.stdout.write(self.style.WARNING(
                f'Eliminados (reset): {stats["eliminados"]}'
            ))
        self.stdout.write(self.style.SUCCESS(
            f'Procesados: {total}\n'
            f'  Creados:       {stats["creados"]}\n'
            f'  Actualizados:  {stats["actualizados"]}\n'
            f'  Sin cambios:   {stats["sin_cambios"]}\n'
            f'  Stock creado:  {stats["con_stock"]}\n'
            f'  Desactivados:  {stats["desactivados"]} (no presentes en JSON)'
        ))
        self.stdout.write(self.style.SUCCESS('-' * 50))
