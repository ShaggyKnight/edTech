"""Carga el catalogo real de perfumes de Ideas Boutique.

Idempotente: corrérselo varias veces no duplica nada. Usa
`get_or_create` por nombre, por SKU y por valor de atributo.

Las fotos NO se cargan aca — el comando crea los productos con
`imagen = None`. La duena las sube despues via el admin Django
(`/admin/catalogo/producto/<pk>/change/`) o desde la pantalla de
galeria del backoffice (`/bodega/productos/<pk>/galeria/`).

Precios: se calculan como un valor de referencia basado en volumen
y concentracion. La duena los ajusta despues con la edicion inline
de precio en `/bodega/productos/` (Bloque 10) o con bulk edit.

Uso:
    python manage.py seed_perfumes_real
    python manage.py seed_perfumes_real --solo-mujer
    python manage.py seed_perfumes_real --solo-hombre
    python manage.py seed_perfumes_real --update-precios  # rescribe precios
"""

from __future__ import annotations

import re
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from catalogo.models import (
    Atributo,
    Familia,
    Producto,
    ProductoVariante,
    ValorAtributo,
)


# ─────────────────────────────────────────────────────────────────────
# Catalogo real (provisto por la duena · mayo 2026).
# Formato de cada fila: (nombre, descripcion, formatos_str).
# ─────────────────────────────────────────────────────────────────────

PERFUMES_MUJER = [
    ('Marvelle Women',
     'Body spray refrescante con notas florales y toques dulces suaves.',
     '200ml, 250ml (Body Spray)'),
    ('Volupté (Oscar de la Renta)',
     'Fragancia floral verde con notas de mimosa, melón, y un fondo de sándalo e incienso.',
     '30ml, 50ml, 100ml (EDT)'),
    ('Rock! (Shakira)',
     'Aroma floral frutal con notas de bergamota, maracuyá, jazmín y flor de azahar.',
     '30ml, 50ml, 80ml (EDT)'),
    ('Eternity for Women (Calvin Klein)',
     'Un clásico floral blanco con notas de lirio, clavel, violeta y un toque de almizcle.',
     '30ml, 50ml, 100ml (EDP)'),
    ('Noa (Cacharel)',
     'Fragancia almizclada y floral con notas de peonía, café, incienso y un toque de cilantro.',
     '30ml, 50ml, 100ml (EDT)'),
    ('Fantasy (Britney Spears)',
     'Aroma dulce y gourmet con notas de chocolate blanco, cupcake, kiwi y orquídea.',
     '30ml, 50ml, 100ml (EDP)'),
    ('Meow! (Katy Perry)',
     'Fragancia dulce frutal con notas de pera, mandarina, vainilla, ámbar y sándalo.',
     '30ml, 50ml, 100ml (EDP)'),
    ('Eternity Reflections (Calvin Klein)',
     'Versión fresca y vibrante con notas frutales, jazmín y un fondo amaderado moderno.',
     '100ml (EDP)'),
    ('Tous Gold',
     'Fragancia floral sofisticada con notas de palo de rosa, gardenia, peonía y cedro.',
     '30ml, 50ml, 90ml (EDP)'),
    ('Seduction Live',
     'Aroma intenso y seductor, generalmente con mezclas de especias y maderas dulces.',
     '200ml, 250ml (Body Spray)'),
    ('Creed Vanille',
     'Body spray con predominancia de vainilla dulce y matices cremosos.',
     '200ml, 250ml (Body Spray)'),
    ('Bouquet Rose',
     'Fragancia floral centrada en la rosa, complementada con notas de almizcle y flores blancas.',
     '50ml, 100ml (EDP/EDT)'),
    ('CK IN2U (Calvin Klein)',
     'Aroma oriental floral con notas de pomelo rosado, orquídea de azúcar y ámbar neón.',
     '50ml, 100ml, 150ml (EDT)'),
    ('Yes I Am (Cacharel)',
     'Fragancia oriental floral con notas de frambuesa, mandarina, flor de jengibre y cardamomo.',
     '30ml, 50ml, 75ml (EDP)'),
    ('The Icon (Antonio Banderas)',
     'Aroma femenino con notas de bergamota, grosella negra, jazmín y sándalo.',
     '50ml, 80ml (EDP)'),
    ('Tommy Girl (Tommy Hilfiger)',
     'Fragancia floral frutal fresca con notas de manzana, camelia, mandarina y madreselva.',
     '30ml, 50ml, 100ml (EDT)'),
    ('Moschino Funny!',
     'Aroma floral frutal chispeante con notas de naranja amarga, té verde, jazmín y peonía.',
     '25ml, 50ml, 100ml (EDT)'),
    ('Can Can (Paris Hilton)',
     'Fragancia floral frutal muy dulce con notas de nectarina, orquídea silvestre y flor de azahar.',
     '30ml, 50ml, 100ml (EDP)'),
    ('Coralia for Women',
     'Fragancia fresca con notas oceánicas y florales ligeras.',
     '50ml, 100ml (EDP/EDT)'),
]
# Nota: la fila #51 del CSV original es duplicado de "Marvelle Women" — get_or_create dedupea.


PERFUMES_HOMBRE = [
    ('212 Men Heroes (Carolina Herrera)',
     'Fougère frutal con notas de pera, jengibre y un fondo de cuero y almizcle.',
     '50ml, 90ml (EDT)'),
    ('Emotion (Rasasi)',
     'Aroma floral frutal con notas de limón, mandarina, jazmín y un fondo de cedro.',
     '50ml (EDP)'),
    ('Hugo Iced (Hugo Boss)',
     'Fragancia aromática acuática con notas de menta helada, té salvaje y vetiver.',
     '75ml, 125ml (EDT)'),
    ('Halloween Man X',
     'Oriental fougère con notas de café, whisky, canela y cardamomo.',
     '50ml, 75ml, 125ml (EDT)'),
    ('Lacoste L.12.12 Magnetic',
     'Aroma aromático especiado con notas de bambú, artemisia, geranio y violeta.',
     '50ml, 100ml (EDT)'),
    ('Armani Code',
     'Fragancia oriental especiada con notas de limón, anís estrellado y cuero.',
     '30ml, 50ml, 75ml, 125ml (EDT)'),
    ('Invictus (Paco Rabanne)',
     'Aroma amaderado acuático con notas marinas, pomelo, laurel y madera de guayaco.',
     '50ml, 100ml, 200ml (EDT)'),
    ('212 VIP Black (Carolina Herrera)',
     'Fragancia aromática fougère con notas de absenta, anís, hinojo y lavanda.',
     '50ml, 100ml, 200ml (EDP)'),
    ('Polo Red (Ralph Lauren)',
     'Aroma amaderado especiado con notas de pomelo rojo, azafrán rojo y madera de cedro.',
     '75ml, 125ml, 200ml (EDT)'),
    ('Bad Boy (Carolina Herrera)',
     'Fragancia oriental especiada con notas de pimienta blanca, pimienta negra y haba tonka.',
     '50ml, 100ml, 150ml (EDT)'),
    ('Phantom (Paco Rabanne)',
     'Aroma fougère aromático con notas de lavanda, cáscara de limón y vainilla de Madagascar.',
     '50ml, 100ml, 150ml (EDT)'),
    ('Light Blue (Dolce & Gabbana)',
     'Fragancia floral frutal con notas de manzana siciliana, cedro y campanilla azul.',
     '25ml, 50ml, 100ml (EDT)'),
    ('Scandal (Jean Paul Gaultier)',
     'Aroma chipre floral con notas de miel, gardenia, naranja sanguina y pachulí.',
     '30ml, 50ml, 80ml (EDP)'),
    ('Mayar (Lattafa)',
     'Aroma floral frutal exótico con notas de lichi, frambuesa y rosa.',
     '100ml (EDP)'),
    ('Club de Nuit Intense',
     'Fragancia floral frutal con notas de limón, grosella negra, manzana y abedul.',
     '105ml, 200ml (EDT/EDP)'),
    ('Guess Girl',
     'Fragancia floral frutal con notas de frambuesa, melón, orquídea brasileña y azucena.',
     '30ml, 50ml, 100ml (EDT)'),
    ('5th Avenue (Elizabeth Arden)',
     'Fragancia floral clásica con notas de tilo, lirio de los valles, lila y magnolia.',
     '30ml, 75ml, 125ml (EDP)'),
    ('Besos de Agatha Ruiz',
     'Aroma floral almizclado con notas de pera, manzana verde y flores de azahar.',
     '30ml, 50ml, 100ml (EDT)'),
    ('Charlie Blue (Revlon)',
     'Fragancia floral fougère con notas de musgo de roble, geranio, sándalo y almizcle.',
     '100ml (EDT)'),
    ('Charlie Red (Revlon)',
     'Aroma oriental floral con notas de gardenia, melocotón, jazmín y clavel.',
     '100ml (EDT)'),
    ('Charlie Silver (Revlon)',
     'Fragancia floral frutal con notas de chabacano, magnolia, durazno y pera.',
     '100ml (EDT)'),
    ('Charlie Gold (Revlon)',
     'Aroma oriental floral con notas de caramelo, canela, durazno y ámbar.',
     '100ml (EDT)'),
    ('Benetton Colors Pink',
     'Fragancia floral frutal con notas de bergamota, maracuyá y rosa.',
     '30ml, 50ml, 80ml (EDT)'),
    ('United Dreams Love',
     'Aroma floral frutal con notas de frambuesa, pera y un fondo de sándalo.',
     '50ml, 80ml (EDT)'),
]


# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────

# Map de abreviaturas a nombres completos de Concentración. La convención
# del repo (ver `seed_demo._atributos`) usa los nombres largos.
CONC_MAP = {
    'edt': 'Eau de Toilette',
    'edp': 'Eau de Parfum',
    'edc': 'Eau de Cologne',
    'cologne': 'Cologne',
    'elixir': 'Elixir',
    'body spray': 'Body Spray',
}

# Orden canónico de concentraciones (de más liviano a más intenso).
ORDEN_CONC = {
    'Body Spray': 0,
    'Cologne': 1,
    'Eau de Cologne': 2,
    'Eau de Toilette': 3,
    'Eau de Parfum': 4,
    'Elixir': 5,
}

# SKU corto de la concentración (para el SKU de la variante).
SKU_CONC = {
    'Eau de Toilette': 'EDT',
    'Eau de Parfum': 'EDP',
    'Eau de Cologne': 'EDC',
    'Cologne': 'COL',
    'Body Spray': 'BSP',
    'Elixir': 'ELX',
}


def parse_formatos(s: str):
    """Parsea '30ml, 50ml, 100ml (EDT/EDP)' -> ([30, 50, 100], ['Eau de Toilette', 'Eau de Parfum']).

    Si no se puede parsear, devuelve ([], []) — el caller debe avisar.
    """
    s = s.strip().rstrip('.')
    m = re.match(r'^(.+?)\s*\(([^)]+)\)\s*$', s)
    if not m:
        return [], []
    vol_part, conc_part = m.groups()
    volumenes = []
    for v in vol_part.split(','):
        v = v.strip()
        m2 = re.match(r'^(\d+)\s*ml$', v, re.IGNORECASE)
        if m2:
            volumenes.append(int(m2.group(1)))
    concs = []
    for c in conc_part.split('/'):
        c = c.strip()
        full = CONC_MAP.get(c.lower(), c)
        if full not in concs:
            concs.append(full)
    return volumenes, concs


# Tablas de precio referencial (CLP). Adaptado a una boutique chilena
# pequeña; la duena los ajusta despues. La idea es que NO arranquen
# todos en cero — el catalogo se ve creible al instante.
PRECIO_EDT = {
    25: 16000, 30: 18000, 50: 25000, 75: 32000, 80: 33000,
    90: 36000, 100: 38000, 105: 39000, 125: 44000, 150: 50000, 200: 60000,
}
PRECIO_EDP = {
    30: 22000, 50: 30000, 75: 38000, 80: 40000, 90: 43000,
    100: 45000, 105: 47000, 125: 52000, 150: 58000, 200: 70000,
}
PRECIO_BODYSPRAY = {200: 8000, 250: 9500}


def precio_referencial(volumen_ml: int, concentracion: str) -> Decimal:
    """Devuelve un precio razonable para la combinacion. La duena
    siempre puede sobreescribirlo despues."""
    if concentracion == 'Body Spray':
        tabla = PRECIO_BODYSPRAY
    elif concentracion == 'Eau de Parfum':
        tabla = PRECIO_EDP
    else:
        tabla = PRECIO_EDT  # EDT, Cologne, Elixir comparten escala
    if volumen_ml in tabla:
        return Decimal(tabla[volumen_ml])
    # Volumen no exacto: interpolar al mas cercano.
    cercano = min(tabla.keys(), key=lambda k: abs(k - volumen_ml))
    return Decimal(tabla[cercano])


def slug_corto(nombre: str, max_len: int = 28) -> str:
    """Slug ASCII apto para SKU. Quita parens y normaliza espacios."""
    # Quitar contenido entre parentesis para que el SKU sea corto.
    sin_parens = re.sub(r'\([^)]*\)', '', nombre).strip()
    # Solo alfanumerico y guiones.
    slug = re.sub(r'[^A-Za-z0-9]+', '-', sin_parens).strip('-').upper()
    return slug[:max_len]


def hacer_sku(nombre: str, volumen_ml: int, concentracion: str) -> str:
    """SKU: PERF-<slug>-<vol>-<conc>. Max 60 chars (limit del modelo)."""
    base = slug_corto(nombre)
    conc = SKU_CONC.get(concentracion, 'X')
    return f'PERF-{base}-{volumen_ml}-{conc}'


# ─────────────────────────────────────────────────────────────────────
# Command
# ─────────────────────────────────────────────────────────────────────

class Command(BaseCommand):
    help = (
        'Carga el catalogo real de perfumes (45 productos con variantes '
        'por volumen y concentracion). Idempotente.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--solo-mujer', action='store_true',
                            help='Solo carga la lista de mujer.')
        parser.add_argument('--solo-hombre', action='store_true',
                            help='Solo carga la lista de hombre.')
        parser.add_argument('--update-precios', action='store_true',
                            help='Reescribe precios de variantes existentes con los valores referenciales.')

    @transaction.atomic
    def handle(self, *args, **opts):
        self.update_precios = opts['update_precios']

        # 1. Familia + atributos.
        familia = self._get_familia_perfumes()
        atr_vol = self._get_atributo_volumen()
        atr_conc = self._get_atributo_concentracion()

        # 2. Pre-poblar valores comunes (no fallar si llegan formatos
        #    raros despues).
        self._precargar_valores(atr_vol, atr_conc)

        # 3. Iterar listas.
        productos = []
        if not opts['solo_hombre']:
            for nombre, desc, formatos in PERFUMES_MUJER:
                productos.append((nombre, desc, formatos, 'mujer'))
        if not opts['solo_mujer']:
            for nombre, desc, formatos in PERFUMES_HOMBRE:
                productos.append((nombre, desc, formatos, 'hombre'))

        stats = {'productos_nuevos': 0, 'productos_existentes': 0,
                 'variantes_nuevas': 0, 'variantes_existentes': 0,
                 'precios_actualizados': 0, 'sin_parsear': []}

        for nombre, desc, formatos, _genero in productos:
            volumenes, concentraciones = parse_formatos(formatos)
            if not volumenes or not concentraciones:
                stats['sin_parsear'].append(f'{nombre} ({formatos})')
                continue
            self._procesar_producto(
                nombre, desc, familia, atr_vol, atr_conc,
                volumenes, concentraciones, stats,
            )

        self._reportar(stats)

    # ─── Helpers internos ────────────────────────────────────────────

    def _get_familia_perfumes(self):
        fam, c = Familia.objects.get_or_create(nombre='Perfumes')
        if c:
            self.stdout.write(self.style.SUCCESS('[OK]   Familia "Perfumes" creada.'))
        return fam

    def _get_atributo_volumen(self):
        atr, c = Atributo.objects.get_or_create(nombre='Volumen')
        if c:
            self.stdout.write(self.style.SUCCESS('[OK]   Atributo "Volumen" creado.'))
        return atr

    def _get_atributo_concentracion(self):
        atr, c = Atributo.objects.get_or_create(nombre='Concentración')
        if c:
            self.stdout.write(self.style.SUCCESS('[OK]   Atributo "Concentración" creado.'))
        return atr

    def _precargar_valores(self, atr_vol, atr_conc):
        # Volumenes comunes en orden ascendente.
        for orden, ml in enumerate([5, 25, 30, 50, 75, 80, 90, 100, 105,
                                    125, 150, 200, 250], start=1):
            ValorAtributo.objects.get_or_create(
                atributo=atr_vol, valor=f'{ml} ml',
                defaults={'orden': orden},
            )
        # Concentraciones.
        for nombre, orden in ORDEN_CONC.items():
            ValorAtributo.objects.get_or_create(
                atributo=atr_conc, valor=nombre,
                defaults={'orden': orden},
            )

    def _procesar_producto(self, nombre, desc, familia, atr_vol, atr_conc,
                           volumenes, concentraciones, stats):
        # Precio base = el mas chico de las variantes posibles.
        candidatos = [
            precio_referencial(v, c)
            for v in volumenes for c in concentraciones
        ]
        precio_base = min(candidatos) if candidatos else Decimal('25000')

        producto, creado = Producto.objects.get_or_create(
            nombre=nombre,
            defaults={
                'familia': familia,
                'descripcion': desc,
                'precio_base': precio_base,
                'tiene_variantes': True,
                'activo': True,
            },
        )
        if creado:
            stats['productos_nuevos'] += 1
        else:
            stats['productos_existentes'] += 1

        # Variantes (un SKU por combinación).
        for vol in volumenes:
            valor_vol, _ = ValorAtributo.objects.get_or_create(
                atributo=atr_vol, valor=f'{vol} ml',
            )
            for conc in concentraciones:
                valor_conc, _ = ValorAtributo.objects.get_or_create(
                    atributo=atr_conc, valor=conc,
                )
                sku = hacer_sku(nombre, vol, conc)
                precio = precio_referencial(vol, conc)

                variante, c_var = ProductoVariante.objects.get_or_create(
                    sku=sku,
                    defaults={
                        'producto': producto,
                        'precio_override': precio,
                        'activa': True,
                    },
                )
                if c_var:
                    variante.valores.add(valor_vol, valor_conc)
                    stats['variantes_nuevas'] += 1
                else:
                    stats['variantes_existentes'] += 1
                    if self.update_precios and variante.precio_override != precio:
                        variante.precio_override = precio
                        variante.save(update_fields=['precio_override', 'modificado'])
                        stats['precios_actualizados'] += 1

    def _reportar(self, stats):
        # ASCII only — el cmd.exe de Windows con codec cp1252 revienta
        # con box-drawing unicode.
        line = '-' * 56
        self.stdout.write('\n' + line)
        self.stdout.write(self.style.SUCCESS('  Carga de perfumes reales · resumen'))
        self.stdout.write(line)
        self.stdout.write(f'  Productos nuevos:       {stats["productos_nuevos"]}')
        self.stdout.write(f'  Productos existentes:   {stats["productos_existentes"]}')
        self.stdout.write(f'  Variantes nuevas:       {stats["variantes_nuevas"]}')
        self.stdout.write(f'  Variantes existentes:   {stats["variantes_existentes"]}')
        if self.update_precios:
            self.stdout.write(f'  Precios actualizados:   {stats["precios_actualizados"]}')
        if stats['sin_parsear']:
            self.stdout.write('')
            self.stdout.write(self.style.WARNING('  No se pudo parsear el formato de:'))
            for nm in stats['sin_parsear']:
                self.stdout.write(self.style.WARNING(f'    - {nm}'))
        self.stdout.write(line)
        self.stdout.write(
            '\n  Siguiente paso: subir fotos via\n'
            '  http://127.0.0.1:8000/admin/catalogo/producto/\n'
            '  o galeria multi-imagen en\n'
            '  http://127.0.0.1:8000/bodega/productos/<pk>/galeria/\n'
        )
