"""Carga las fotos PLACEHOLDER de perfumes del handoff (Ideas 14).

⚠️ Estas 9 imágenes son renders de referencia generados con IA — el
packaging puede diferir del producto real (algunos traen typos del
generador). Sirven para no dejar el catálogo vacío mientras la dueña
toma las fotos reales. NO son fotos de venta definitivas: los productos
afectados se marcan en la descripción para re-fotografiar.

Idempotente:
  - Por defecto NO pisa una imagen ya cargada (para no tapar una foto
    real con el placeholder). Usá --force para sobreescribir.
  - Re-correrlo sin --force solo carga las que faltan.

Uso:
    python manage.py cargar_fotos_perfumes
    python manage.py cargar_fotos_perfumes --carpeta otra/ruta --force
"""
import os

from django.core.files import File
from django.core.management.base import BaseCommand
from django.db import transaction

from catalogo.models import Producto


# Carpeta por defecto: donde quedaron los assets copiados.
CARPETA_DEFAULT = os.path.join('edTech', 'static', 'img', 'ideas', 'perfumes')

# archivo -> nombre EXACTO del Producto en la DB.
# Para los nombres ambiguos (Emotion / Lacoste tienen varias variantes)
# se eligió el match más razonable; como son placeholders a re-fotografiar
# da igual sobre cuál de los gemelos cae. El comando reporta cada uno.
MAPEO = {
    'absolu-women.png':          'Absolu Women',
    'versace-eau-fraiche.png':   'Versace Man Eau Fraiche',
    '212-men-heroes.png':        '212 Men Heroes (Carolina Herrera)',
    'emotion-men-body-spray.png': 'Emotion Homme Aerosol',
    'emotion-for-men.png':       'Emotion (Rasasi)',
    'hugo-iced.png':             'Hugo Iced',
    'halloween-man-x.png':       'Halloween Man X',
    'lacoste-l1212.png':         'Lacoste L.12.12 Blanc',
    'armani-code.png':           'Armani Code',
}

# Texto que se agrega a la descripción para marcar la foto como provisional.
MARCA_PLACEHOLDER = '[foto provisional — re-fotografiar]'


class Command(BaseCommand):
    help = 'Carga fotos placeholder de perfumes desde el handoff (Ideas 14).'

    def add_arguments(self, parser):
        parser.add_argument('--carpeta', default=CARPETA_DEFAULT)
        parser.add_argument(
            '--force', action='store_true',
            help='Sobreescribe imágenes ya cargadas (por defecto las respeta).',
        )

    @transaction.atomic
    def handle(self, *args, **opts):
        carpeta = opts['carpeta']
        force = opts['force']

        stats = {'cargadas': 0, 'saltadas': 0, 'no_encontradas': 0, 'sin_archivo': 0}

        for archivo, nombre in MAPEO.items():
            ruta = os.path.join(carpeta, archivo)
            if not os.path.exists(ruta):
                self.stdout.write(self.style.ERROR(
                    f'  [X] archivo no existe: {ruta}'))
                stats['sin_archivo'] += 1
                continue

            producto = Producto.objects.filter(nombre=nombre).first()
            if not producto:
                self.stdout.write(self.style.WARNING(
                    f'  [?] producto no existe: {nombre!r} -- saltado'))
                stats['no_encontradas'] += 1
                continue

            if producto.imagen and not force:
                self.stdout.write(
                    f'  = {nombre}: ya tiene imagen, saltado (usá --force)')
                stats['saltadas'] += 1
                continue

            with open(ruta, 'rb') as f:
                producto.imagen.save(archivo, File(f), save=False)

            # Marcar como placeholder en la descripción (idempotente).
            desc = producto.descripcion or ''
            if MARCA_PLACEHOLDER not in desc:
                producto.descripcion = (desc + '\n\n' + MARCA_PLACEHOLDER).strip()

            producto.save()
            self.stdout.write(self.style.SUCCESS(
                f'  [OK] {nombre}  <-  {archivo}'))
            stats['cargadas'] += 1

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('-' * 50))
        self.stdout.write(self.style.SUCCESS(
            f'Cargadas:        {stats["cargadas"]}\n'
            f'Saltadas (tenían foto): {stats["saltadas"]}\n'
            f'Producto no existe:     {stats["no_encontradas"]}\n'
            f'Archivo no existe:      {stats["sin_archivo"]}'
        ))
        self.stdout.write(self.style.SUCCESS('-' * 50))
        if stats['cargadas']:
            self.stdout.write(self.style.WARNING(
                '\nRecordá: son placeholders IA. Los productos quedaron '
                f'marcados con "{MARCA_PLACEHOLDER}" en la descripción '
                'para re-fotografiar.'
            ))
