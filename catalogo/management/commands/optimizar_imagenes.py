"""Reduce las imagenes de productos ya subidas para que pesen menos.

Uso:
    python manage.py optimizar_imagenes              # dry-run, solo lista
    python manage.py optimizar_imagenes --aplicar    # de verdad las reescribe

Procesa:
  - `Producto.imagen` (portada)
  - `ProductoImagen.imagen` (galeria)

Aplica los umbrales y heuristicas de `catalogo.imagenes.optimizar_imagen_field`:
  - max lado 1400 px
  - JPEG quality 85, progressive
  - PNG se mantiene solo si tiene transparencia real
  - se saltean las que ya cumplen los umbrales

IMPORTANTE: la version `--aplicar` REESCRIBE el archivo en disco. Si
queres conservar los originales, hace un backup de `media/productos/`
antes de correrlo.
"""

from django.core.management.base import BaseCommand

from catalogo.imagenes import optimizar_imagen_field
from catalogo.models import Producto, ProductoImagen


class Command(BaseCommand):
    help = 'Optimiza las imagenes de productos (resize + recompress).'

    def add_arguments(self, parser):
        parser.add_argument(
            '--aplicar', action='store_true',
            help='Si se omite, solo lista las imagenes que SERIAN optimizadas (dry-run).',
        )

    def handle(self, *args, **opts):
        aplicar = opts['aplicar']
        if not aplicar:
            self.stdout.write(self.style.WARNING(
                'DRY-RUN: solo lista — usa --aplicar para reescribir los archivos.\n'
            ))

        total_procesadas = 0
        total_ahorro = 0  # bytes

        self.stdout.write(self.style.NOTICE('Portadas de producto:'))
        for p in Producto.objects.exclude(imagen='').exclude(imagen__isnull=True):
            cambio = self._procesar(p.imagen, aplicar)
            if cambio is not None:
                total_procesadas += 1
                total_ahorro += cambio
                if aplicar:
                    p.save(update_fields=['imagen'])

        self.stdout.write('')
        self.stdout.write(self.style.NOTICE('Imagenes de galeria:'))
        for ig in ProductoImagen.objects.all():
            cambio = self._procesar(ig.imagen, aplicar)
            if cambio is not None:
                total_procesadas += 1
                total_ahorro += cambio
                if aplicar:
                    ig.save(update_fields=['imagen'])

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(
            f'Total: {total_procesadas} imagen(es) ' +
            ('reducidas' if aplicar else 'serian reducidas') +
            f' — ahorro: {total_ahorro // 1024} KB.'
        ))
        if not aplicar and total_procesadas > 0:
            self.stdout.write(self.style.WARNING(
                '\nPara aplicar: python manage.py optimizar_imagenes --aplicar'
            ))

    def _procesar(self, image_field, aplicar):
        """Procesa una imagen. Retorna bytes ahorrados o None si no aplica."""
        try:
            tamaño_antes = image_field.size
        except Exception as e:
            self.stdout.write(f'  ! {image_field.name}: no se pudo leer ({e})')
            return None

        if aplicar:
            cambiada, mensaje = optimizar_imagen_field(image_field)
            if not cambiada:
                return None
            tamaño_despues = image_field.size
            ahorro = tamaño_antes - tamaño_despues
            self.stdout.write(self.style.SUCCESS(
                f'  OK  {mensaje}  ({tamaño_antes // 1024} -> {tamaño_despues // 1024} KB)'
            ))
            return ahorro
        else:
            # Dry-run: simulamos en memoria sin escribir.
            from catalogo.imagenes import _ya_optimizada
            if _ya_optimizada(image_field):
                return None
            self.stdout.write(
                f'  ?  {image_field.name}  ({tamaño_antes // 1024} KB -> seria reducida)'
            )
            # Estimacion conservadora del ahorro para el dry-run: 70%.
            return int(tamaño_antes * 0.7)
