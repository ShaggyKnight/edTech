"""Prende o apaga el modo mantenimiento del sitio.

El modo mantenimiento se controla con un archivo flag (default
`/srv/ideas/MAINTENANCE` en prod, configurable via env). Cuando existe,
el publico ve una pagina de "volvemos pronto" con HTTP 503; el staff
sigue navegando normal.

Uso:
    python manage.py mantenimiento on        # encender
    python manage.py mantenimiento off       # apagar
    python manage.py mantenimiento estado    # ver si esta on/off
    python manage.py mantenimiento           # alias de "estado"

Tambien se puede tocar el archivo directo:
    sudo -u ideas touch /srv/ideas/MAINTENANCE
    sudo -u ideas rm    /srv/ideas/MAINTENANCE
"""

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = 'Enciende/apaga el modo mantenimiento del sitio publico.'

    def add_arguments(self, parser):
        parser.add_argument(
            'accion', nargs='?', default='estado',
            choices=['on', 'off', 'estado'],
            help='on = encender, off = apagar, estado = consultar (default).',
        )

    def handle(self, *args, **opts):
        accion = opts['accion']
        flag = getattr(settings, 'MAINTENANCE_FLAG_FILE', None)
        if not flag:
            raise CommandError('MAINTENANCE_FLAG_FILE no esta configurado.')
        ruta = Path(flag)

        if accion == 'on':
            ruta.parent.mkdir(parents=True, exist_ok=True)
            ruta.touch(exist_ok=True)
            self.stdout.write(self.style.WARNING(
                f'Modo mantenimiento ENCENDIDO. Archivo: {ruta}'
            ))
            self.stdout.write(
                'El publico ahora ve la pagina "Volvemos pronto" (HTTP 503).'
            )
            self.stdout.write('El staff sigue navegando normal.')
        elif accion == 'off':
            if ruta.exists():
                ruta.unlink()
                self.stdout.write(self.style.SUCCESS(
                    f'Modo mantenimiento APAGADO. Archivo eliminado: {ruta}'
                ))
            else:
                self.stdout.write(self.style.NOTICE(
                    f'El modo ya estaba apagado (archivo no existe: {ruta}).'
                ))
        else:  # estado
            if ruta.exists():
                self.stdout.write(self.style.WARNING(
                    f'Modo mantenimiento ENCENDIDO. Archivo: {ruta}'
                ))
            else:
                self.stdout.write(self.style.SUCCESS(
                    f'Modo mantenimiento apagado. (No existe: {ruta})'
                ))
