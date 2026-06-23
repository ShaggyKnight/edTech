"""Carga el CATASTRO REAL de perfumes (base definitiva) desde JSON.

A diferencia de `seed_perfumes_real` (formato viejo), este comando lee el
catastro provisto por la duena el 22-06-2026, donde cada fila es un
perfume real en inventario:

    {
      "nombre": "L.12.12 Blanc", "marca": "Lacoste",
      "concentracion": "Eau de Parfum", "medida": "100 ml / 3.3 Fl. Oz.",
      "cantidad": 1, "familia_olfativa": "Amaderada Aromatica",
      "descripcion": "...", "notas_clave": ["Toronja", "Cardamomo", ...]
    }

Modelo resultante (mismo esquema que el resto del catalogo):
    Producto (marca + nombre)  tiene_variantes=True, familia "Perfumes"
      .marca / .concentracion(codigo) / .familia_olfativa / .notas_clave
      .genero (inferido del nombre)
      ProductoVariante  valores = [Volumen, Concentracion(display)]
        StockTienda(tienda online).cantidad = "cantidad" del catastro

Acciones:
  - Upsert de cada perfume del catastro (match robusto por nombre-nucleo,
    ignorando marca como prefijo o "(marca)" al final, para no duplicar).
  - Stock online = cantidad (es inventario real → se SETEA, no se suma).
  - Desactiva (activo=False, NO borra) los perfumes en DB que NO estan en
    el catastro. Reversible.

Seguridad: por defecto es DRY-RUN (no escribe nada, solo lista el plan).
Usar --aplicar para escribir.

Uso:
    python manage.py cargar_catastro_perfumes              # dry-run
    python manage.py cargar_catastro_perfumes --aplicar    # escribe
    python manage.py cargar_catastro_perfumes --no-desactivar  # no toca los no listados
"""
from __future__ import annotations

import json
import re
import unicodedata
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from catalogo.models import (
    Atributo, Familia, Producto, ProductoVariante, ValorAtributo,
)
from catalogo.sku import generar_sku_unico

DATA_FILE = Path(settings.BASE_DIR) / 'catalogo' / 'data' / 'catastro_perfumes.json'

# Familias consideradas "perfumeria" para el barrido de desactivacion.
FAMILIAS_PERFUMERIA = ('Perfumes', 'Fragancias premium')

# concentracion (texto del catastro) -> codigo del modelo.
CONC_MAP = {
    'eau de parfum': 'EDP', 'edp': 'EDP', 'parfum': 'EDP',
    'extrait de parfum': 'EDP', 'extrait': 'EDP',
    'eau de toilette': 'EDT', 'edt': 'EDT',
    'eau de cologne': 'EDC', 'cologne': 'EDC', 'edc': 'EDC',
    'body spray': 'BODY',
}
# codigo -> display para el chip de la variante.
CONC_DISPLAY = {'EDP': 'EDP', 'EDT': 'EDT', 'EDC': 'EDC',
                'BODY': 'Body Spray', 'SET': 'Set'}

_RE_PAREN = re.compile(r'\s*\([^)]*\)\s*$')   # "(Calvin Klein)" al final
_RE_ML = re.compile(r'(\d+(?:\.\d+)?)\s*ml', re.I)
_RE_HOMBRE = re.compile(r'\b(men|man|him|homme|hombre|masculin\w*)\b', re.I)
_RE_MUJER = re.compile(r'\b(women|woman|her|femme|mujer|feminin\w*|pink)\b', re.I)


def _sin_acentos(s: str) -> str:
    """Quita diacriticos: 'Mediterráneo' -> 'mediterraneo', 'Fraîche' -> 'fraiche'."""
    return ''.join(c for c in unicodedata.normalize('NFKD', s)
                   if not unicodedata.combining(c))


def _core_name(nombre: str, marca: str) -> str:
    """Clave canonica 'marca nombre' para matchear, robusta a acentos y a
    como este guardada la marca (campo, prefijo o '(Marca)' al final).

    Ejemplos que caen TODOS a la misma clave:
      catastro  nombre='L.12.12 Blanc'   marca='Lacoste'
      DB        nombre='Lacoste L.12.12 Blanc'   marca='Lacoste'
      catastro  nombre='CK IN2U Him'     marca='Calvin Klein'
      DB        nombre='CK IN2U Him (Calvin Klein)'  marca=''(vacio)
    """
    # Si el campo marca esta vacio pero el nombre trae '(Marca)' al final,
    # usamos ese parentesis como marca efectiva.
    paren = _RE_PAREN.search(nombre)
    marca_ef = (marca or '').strip() or (
        paren.group(0).strip(' ()') if paren else '')

    n = _RE_PAREN.sub('', nombre.strip())
    n = _sin_acentos(n).lower()
    m = _sin_acentos(marca_ef).lower()
    if m and not n.startswith(m):
        n = f'{m} {n}'
    return re.sub(r'\s+', ' ', n).strip()


def _final_name(nombre: str, marca: str) -> str:
    """Nombre de display para productos NUEVOS: 'Marca Nombre' sin duplicar."""
    n = _RE_PAREN.sub('', nombre.strip())
    if marca and not n.lower().startswith(marca.lower()):
        return f'{marca} {n}'.strip()
    return n


def _conc_codigo(texto: str, es_set: bool) -> str:
    if es_set:
        return 'SET'
    t = (texto or '').strip().lower()
    if t in CONC_MAP:
        return CONC_MAP[t]
    # Ambiguos "EdP / EdT", "Parfum / EdT": tomar el primer token reconocible.
    for parte in re.split(r'[/|]', t):
        parte = parte.strip()
        if parte in CONC_MAP:
            return CONC_MAP[parte]
    return ''  # desconocido -> vacio (el operador lo ajusta en el form)


def _genero(nombre: str, notas: list[str]) -> str:
    blob = (nombre + ' ' + ' '.join(notas or [])).lower()
    h = bool(_RE_HOMBRE.search(blob))
    m = bool(_RE_MUJER.search(blob))
    if h and not m:
        return 'hombre'
    if m and not h:
        return 'mujer'
    return 'unisex'


def _parse_volumen(medida: str):
    """Devuelve (volumen_label, es_set). volumen_label None si no hay ml."""
    s = (medida or '').replace('~', '').strip()
    mls = _RE_ML.findall(s)
    if not mls:
        return None, False
    if '+' in s:                      # "50 ml + 75 ml" -> set
        return ' + '.join(f'{x} ml' for x in mls), True
    if '-' in s and len(mls) >= 2:    # "100 ml - 200 ml" -> rango
        return f'{mls[0]}-{mls[-1]} ml', False
    return f'{mls[0]} ml', False


def _orden_volumen(volumen_label: str) -> int:
    m = _RE_ML.search(volumen_label or '')
    return int(float(m.group(1))) if m else 999


class Command(BaseCommand):
    help = 'Carga el catastro real de perfumes (base definitiva) desde JSON.'

    def add_arguments(self, parser):
        parser.add_argument('--archivo', default=str(DATA_FILE))
        parser.add_argument(
            '--aplicar', action='store_true',
            help='Escribe los cambios. Sin esto es DRY-RUN (no toca nada).',
        )
        parser.add_argument(
            '--no-desactivar', action='store_true',
            help='No desactiva los perfumes que no estan en el catastro.',
        )
        parser.add_argument(
            '--mantener-tallas-extra', action='store_true',
            help='Por defecto, las tallas/variantes de un perfume que el '
                 'catastro NO lista quedan en stock 0 (agotadas), porque el '
                 'catastro es el inventario real. Con esta flag se conservan '
                 'con su stock anterior.',
        )

    def handle(self, *args, **opts):
        archivo = Path(opts['archivo'])
        if not archivo.exists():
            raise CommandError(f'No existe el catastro: {archivo}')

        aplicar = opts['aplicar']
        desactivar = not opts['no_desactivar']
        zerar_extra = not opts['mantener_tallas_extra']

        with archivo.open(encoding='utf-8') as f:
            catastro = json.load(f)

        if not aplicar:
            self.stdout.write(self.style.WARNING(
                'DRY-RUN: no se escribe nada. Usa --aplicar para confirmar.\n'))

        familia = Familia.objects.get_or_create(nombre='Perfumes')[0]
        atr_vol, _ = Atributo.objects.get_or_create(nombre='Volumen')
        atr_conc, _ = Atributo.objects.get_or_create(nombre='Concentracion')
        tienda = self._tienda_online()
        if not tienda:
            self.stdout.write(self.style.WARNING(
                'Sin tienda online (ECOMMERCE_TIENDA_ID) — no se cargara stock.\n'))

        # Index de perfumes existentes por nombre-nucleo.
        fam_ids = list(Familia.objects
                       .filter(nombre__in=FAMILIAS_PERFUMERIA)
                       .values_list('pk', flat=True))
        existentes = list(Producto.objects.filter(familia_id__in=fam_ids))
        db_index = {}
        for p in existentes:
            db_index.setdefault(_core_name(p.nombre, p.marca), p)

        stats = {'creados': 0, 'actualizados': 0, 'sin_cambios': 0,
                 'stock_set': 0, 'desactivados': 0, 'tallas_zeradas': 0,
                 'genero': {}}
        cores_catastro = set()
        avisos = []

        with transaction.atomic():
            for entry in catastro:
                core = self._procesar(
                    entry, familia, atr_vol, atr_conc, tienda,
                    db_index, stats, avisos, aplicar, zerar_extra,
                )
                cores_catastro.add(core)

            if desactivar:
                stats['desactivados'] = self._desactivar(
                    existentes, cores_catastro, aplicar)

            if not aplicar:
                transaction.set_rollback(True)

        self._reportar(stats, len(catastro), avisos, aplicar, desactivar)

    # ─────────────────────────────────────────────────────────────────

    def _tienda_online(self):
        from bodega.models import Tienda
        tid = getattr(settings, 'ECOMMERCE_TIENDA_ID', None)
        if tid:
            t = Tienda.objects.filter(pk=tid).first()
            if t:
                return t
        return Tienda.objects.filter(activa=True).first()

    def _procesar(self, entry, familia, atr_vol, atr_conc, tienda,
                  db_index, stats, avisos, aplicar, zerar_extra):
        nombre_raw = entry['nombre']
        marca = (entry.get('marca') or '').strip()
        core = _core_name(nombre_raw, marca)

        notas_list = entry.get('notas_clave') or []
        notas = ' · '.join(n.strip() for n in notas_list if n.strip())
        volumen_label, es_set = _parse_volumen(entry.get('medida', ''))
        conc_cod = _conc_codigo(entry.get('concentracion', ''), es_set)
        genero = _genero(nombre_raw, notas_list)
        stats['genero'][genero] = stats['genero'].get(genero, 0) + 1
        cantidad = int(entry.get('cantidad') or 0)

        meta = {
            'familia': familia,
            'marca': marca,
            'concentracion': conc_cod,
            'familia_olfativa': entry.get('familia_olfativa', '').strip(),
            'notas_clave': notas,
            'descripcion': entry.get('descripcion', '').strip(),
            'genero': genero,
            'tiene_variantes': True,
            'activo': True,
        }

        # Escritura SIEMPRE dentro de la transaccion. En dry-run, el caller
        # hace set_rollback(True) al final → nada queda en la DB, pero los
        # conteos/avisos son reales (simulacion fiel).
        producto = db_index.get(core)
        if producto is None:
            nombre_final = _final_name(nombre_raw, marca)
            # Red de seguridad: si ya existe un producto con ese nombre exacto
            # (que el canon no atrapo), lo reusamos en vez de chocar con el
            # UNIQUE de Producto.nombre.
            producto = Producto.objects.filter(nombre=nombre_final).first()
        if producto is None:
            producto = Producto.objects.create(
                nombre=nombre_final, precio_base=Decimal('0'), **meta)
            db_index[core] = producto
            stats['creados'] += 1
            self.stdout.write(self.style.SUCCESS(f'  + NUEVO  {nombre_final}'))
        else:
            cambios = [k for k, v in meta.items() if getattr(producto, k) != v]
            if cambios:
                for k, v in meta.items():
                    setattr(producto, k, v)
                producto.save()
                stats['actualizados'] += 1
                self.stdout.write(f'  ~ actualiza {producto.nombre}')
            else:
                stats['sin_cambios'] += 1

        # Variante (Volumen + Concentracion) + stock online.
        variante = self._get_or_create_variante(
            producto, atr_vol, atr_conc, volumen_label, conc_cod)
        otras = list(producto.variantes.exclude(pk=variante.pk))
        if otras:
            avisos.append(
                f'{producto.nombre}: {len(otras)} variante(s) extra ademas de '
                f'"{volumen_label}" (catastro solo lista esa).')
        if tienda:
            from bodega.models import StockTienda
            # Stock de la talla del catastro = cantidad real.
            st, _ = StockTienda.objects.get_or_create(
                tienda=tienda, variante=variante,
                defaults={'cantidad': cantidad})
            if st.cantidad != cantidad:
                st.cantidad = cantidad
                st.save(update_fields=['cantidad'])
            stats['stock_set'] += 1

            # Tallas que el catastro NO lista -> stock 0 (agotadas), porque
            # el catastro es el inventario real de hoy.
            if zerar_extra and otras:
                n = (StockTienda.objects
                     .filter(tienda=tienda, variante__in=otras)
                     .exclude(cantidad=0)
                     .update(cantidad=0))
                stats['tallas_zeradas'] += n

        return core

    def _get_or_create_variante(self, producto, atr_vol, atr_conc,
                                volumen_label, conc_cod):
        valores = []
        if volumen_label:
            v, _ = ValorAtributo.objects.get_or_create(
                atributo=atr_vol, valor=volumen_label,
                defaults={'orden': _orden_volumen(volumen_label)})
            valores.append(v)
        if conc_cod:
            disp = CONC_DISPLAY.get(conc_cod, conc_cod)
            c, _ = ValorAtributo.objects.get_or_create(
                atributo=atr_conc, valor=disp)
            valores.append(c)
        valores_set = set(valores)

        for var in producto.variantes.all().prefetch_related('valores'):
            if set(var.valores.all()) == valores_set:
                return var

        sku = generar_sku_unico(
            marca=producto.marca, nombre=producto.nombre,
            valores=[v.valor for v in valores])
        var = ProductoVariante.objects.create(
            producto=producto, sku=sku, activa=True)
        var.valores.set(valores_set)
        return var

    def _desactivar(self, existentes, cores_catastro, aplicar):
        n = 0
        for p in existentes:
            if not p.activo:
                continue
            if _core_name(p.nombre, p.marca) not in cores_catastro:
                self.stdout.write(self.style.WARNING(f'  - desactiva {p.nombre}'))
                if aplicar:
                    p.activo = False
                    p.save(update_fields=['activo'])
                n += 1
        return n

    def _reportar(self, stats, total, avisos, aplicar, desactivar):
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('=' * 56))
        verbo = '' if aplicar else '(DRY-RUN) '
        self.stdout.write(self.style.SUCCESS(
            f'{verbo}Catastro: {total} perfumes\n'
            f'  Nuevos:        {stats["creados"]}\n'
            f'  Actualizados:  {stats["actualizados"]}\n'
            f'  Sin cambios:   {stats["sin_cambios"]}\n'
            f'  Stock seteado: {stats["stock_set"]}\n'
            f'  Tallas extra a 0: {stats["tallas_zeradas"]}\n'
            f'  Desactivados:  {stats["desactivados"]}'
            f'{"" if desactivar else " (--no-desactivar)"}\n'
            f'  Genero inferido: {dict(stats["genero"])}'
        ))
        if avisos:
            self.stdout.write(self.style.WARNING(
                f'\nAvisos ({len(avisos)} productos con variantes extra '
                f'al catastro — revisar stock de esas tallas):'))
            for a in avisos[:30]:
                self.stdout.write(self.style.WARNING(f'  ! {a}'))
        self.stdout.write(self.style.SUCCESS('=' * 56))
        if not aplicar:
            self.stdout.write(self.style.WARNING(
                '\nDRY-RUN — nada se escribio. Revisa el plan y corre con '
                '--aplicar para confirmar.'))
