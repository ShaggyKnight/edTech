"""Genera las miniaturas WebP que falten de las fotos de producto.

Uso:
    python manage.py generar_miniaturas            # solo las que faltan
    python manage.py generar_miniaturas --forzar   # rehace todas

Idempotente y rapido cuando ya existen: deploy.sh lo corre en cada
despliegue. Ver catalogo/miniaturas.py.
"""
from django.core.management.base import BaseCommand

from catalogo import miniaturas
from catalogo.models import Producto, ProductoImagen


class Command(BaseCommand):
    help = 'Genera las miniaturas WebP (400 y 800 px) de las fotos de producto.'

    def add_arguments(self, parser):
        parser.add_argument('--forzar', action='store_true',
                            help='Rehace tambien las que ya existen.')

    def handle(self, *args, **opts):
        creadas = errores = 0
        objetos = list(Producto.objects.exclude(imagen='')) + list(
            ProductoImagen.objects.exclude(imagen=''))
        for obj in objetos:
            try:
                creadas += len(miniaturas.generar(obj.imagen, forzar=opts['forzar']))
            except Exception as exc:  # una foto rota no frena las demas
                errores += 1
                self.stderr.write(f'  [X] {obj.imagen.name}: {exc}')
        self.stdout.write(self.style.SUCCESS(
            f'Miniaturas: {creadas} creadas, {len(objetos)} fotos revisadas, {errores} con error.'
        ))
