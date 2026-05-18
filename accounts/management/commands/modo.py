"""Cambia el modo del sitio publico: normal | landing | mantenimiento.

Modos:
  - normal          tienda completa abierta al publico.
  - landing         solo se ve la home (`/`) y `/info/`; el resto
                    redirige a la home. Util para soft-launch.
  - mantenimiento   pagina "Volvemos pronto" en todo el sitio (HTTP 503).

En cualquier modo, el staff (is_staff=True) sigue navegando normal,
y los paths /admin/, ADMIN_URL custom, /cuenta/login/, /static/, /media/
y /healthz quedan accesibles para que la duena pueda loguearse y volver
al modo normal.

Uso:
    python manage.py modo                 # consultar estado
    python manage.py modo normal
    python manage.py modo landing
    python manage.py modo mantenimiento

Los modos se controlan con dos archivos flag (definidos en settings).
Cambiar de modo es instantaneo — no requiere restart de gunicorn. Si
los dos flags estan presentes a la vez, mantenimiento gana.
"""

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = 'Cambia el modo del sitio (normal/landing/mantenimiento).'

    def add_arguments(self, parser):
        parser.add_argument(
            'modo', nargs='?', default='estado',
            choices=['normal', 'landing', 'mantenimiento', 'estado'],
            help='Modo a setear, o "estado" (default) para consultar.',
        )

    def handle(self, *args, **opts):
        modo = opts['modo']
        mant = self._path('MAINTENANCE_FLAG_FILE')
        land = self._path('LANDING_ONLY_FLAG_FILE')

        if modo == 'normal':
            self._desactivar(mant)
            self._desactivar(land)
            self.stdout.write(self.style.SUCCESS('Modo NORMAL — tienda abierta al publico.'))
        elif modo == 'landing':
            self._desactivar(mant)  # mant gana sobre landing — apagarlo
            self._activar(land)
            self.stdout.write(self.style.WARNING(
                'Modo LANDING — solo se ve la home. El resto redirige a /.'
            ))
        elif modo == 'mantenimiento':
            self._activar(mant)
            self.stdout.write(self.style.WARNING(
                'Modo MANTENIMIENTO — publico ve "Volvemos pronto" (HTTP 503).'
            ))
        else:  # estado
            self._mostrar_estado(mant, land)
            return

        # Despues de cambiar, mostrar estado final para confirmar.
        self.stdout.write('')
        self._mostrar_estado(mant, land)

    def _path(self, setting_name):
        valor = getattr(settings, setting_name, None)
        if not valor:
            raise CommandError(f'{setting_name} no esta configurado en settings.')
        return Path(valor)

    def _activar(self, ruta):
        # No intentamos crear los directorios padre — eso requeriria
        # permisos de root en /srv. El deploy de produccion crea
        # /srv/ideas/ con chown a `ideas`, asi que el padre ya existe.
        # Si no existe, le decimos al operador como arreglarlo en vez
        # de tirar un PermissionError feo del os.mkdir.
        if not ruta.parent.exists():
            raise CommandError(
                f'El directorio {ruta.parent} no existe. Crealo primero:\n'
                f'    sudo mkdir -p {ruta.parent}\n'
                f'    sudo chown ideas:ideas {ruta.parent}'
            )
        try:
            ruta.touch(exist_ok=True)
        except PermissionError as e:
            raise CommandError(
                f'No se puede escribir en {ruta}. Permisos:\n'
                f'    sudo chown ideas:ideas {ruta.parent}\n'
                f'    sudo chmod u+w {ruta.parent}\n'
                f'Error original: {e}'
            )

    def _desactivar(self, ruta):
        if ruta.exists():
            try:
                ruta.unlink()
            except PermissionError as e:
                raise CommandError(
                    f'No se puede borrar {ruta}. Permisos: '
                    f'sudo chown ideas:ideas {ruta}. Error: {e}'
                )

    def _mostrar_estado(self, mant, land):
        if mant.exists():
            self.stdout.write(self.style.WARNING(
                f'Estado actual: MANTENIMIENTO ({mant} presente).'
            ))
        elif land.exists():
            self.stdout.write(self.style.WARNING(
                f'Estado actual: LANDING ({land} presente).'
            ))
        else:
            self.stdout.write(self.style.SUCCESS(
                'Estado actual: NORMAL (ningun flag presente).'
            ))
