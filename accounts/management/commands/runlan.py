"""Atajo para levantar el dev server accesible en la red local.

Equivalente a `python manage.py runserver 0.0.0.0:8000` pero antes de
arrancar muestra las IPs LAN del equipo y las URLs que usar desde otros
dispositivos (celular, laptop, etc) conectados a la misma red.

Uso:
    python manage.py runlan
    python manage.py runlan --port 8080
"""
import socket

from django.core.management.base import BaseCommand
from django.core.management import call_command


def _ips_locales():
    """Devuelve lista de IPv4 locales (excluyendo loopback)."""
    ips = []
    try:
        # Truco: conexión "fake" a una IP externa para que el SO devuelva
        # la IP de la interfaz que usaría para salir a Internet.
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('10.255.255.255', 1))
        ips.append(s.getsockname()[0])
        s.close()
    except Exception:
        pass
    # También listamos todas las IPs del hostname.
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = info[4][0]
            if ip not in ips and not ip.startswith('127.'):
                ips.append(ip)
    except Exception:
        pass
    return ips


class Command(BaseCommand):
    help = 'Dev server accesible desde la red local (0.0.0.0:8000).'

    def add_arguments(self, parser):
        parser.add_argument('--port', default='8000',
                            help='Puerto a usar (default 8000).')

    def handle(self, *args, **opts):
        port = opts['port']
        ips = _ips_locales()
        self.stdout.write(self.style.NOTICE(
            '\n══════════════════════════════════════════════════════════'
        ))
        self.stdout.write(self.style.SUCCESS('  Ideas Boutique — dev en red local'))
        self.stdout.write(self.style.NOTICE(
            '──────────────────────────────────────────────────────────'
        ))
        self.stdout.write(f'  Local:    http://127.0.0.1:{port}/')
        for ip in ips:
            self.stdout.write(self.style.SUCCESS(f'  Red LAN:  http://{ip}:{port}/'))
        self.stdout.write(self.style.NOTICE(
            '\n  Desde otro dispositivo en la misma red, abrí cualquiera de\n'
            '  las URLs "Red LAN" — celular, otra laptop, tablet.\n'
            '  Asegurate que tu .env permita la IP en ALLOWED_HOSTS.\n'
            '══════════════════════════════════════════════════════════\n'
        ))
        call_command('runserver', f'0.0.0.0:{port}')
