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
        firewall_ok = self._regla_firewall_existe(port)
        red_publica = self._red_activa_es_publica()
        rule_perfiles = self._perfiles_regla_firewall(port)
        # Solo ASCII en stdout — en Windows cmd.exe el codec cp1252 no
        # acepta caracteres como ═ y revienta el comando.
        sep = '=' * 60
        self.stdout.write(self.style.NOTICE('\n' + sep))
        self.stdout.write(self.style.SUCCESS('  Ideas Boutique - dev en red local'))
        self.stdout.write(self.style.NOTICE('-' * 60))
        self.stdout.write(f'  Local:    http://127.0.0.1:{port}/')
        for ip in ips:
            self.stdout.write(self.style.SUCCESS(f'  Red LAN:  http://{ip}:{port}/'))
        if firewall_ok is False:
            self.stdout.write(self.style.WARNING(
                '\n  [!] Firewall de Windows: no veo regla para el puerto.'
                '\n      Ejecuta scripts/firewall_open_8000.bat como Administrador.'
                '\n      Sin esa regla, otros dispositivos no van a poder conectar.'
            ))
        # Bug comun: red WiFi clasificada como Public pero el firewall
        # solo deja pasar Private+Domain. Otros dispositivos no conectan.
        if red_publica and rule_perfiles and 'public' not in rule_perfiles:
            self.stdout.write(self.style.WARNING(
                '\n  [!] Tu red Wi-Fi esta como PUBLIC pero el firewall solo'
                '\n      permite Private+Domain. Otros dispositivos NO van a'
                '\n      conectar aunque la regla este habilitada. Fix rapido:'
                '\n        1) PowerShell como Admin:'
                '\n           Set-NetConnectionProfile -Name "<tu wifi>" '
                '-NetworkCategory Private'
                '\n        2) O re-correr scripts/firewall_open_8000.bat'
                '\n           (ahora incluye profile=public).'
            ))
        self.stdout.write(self.style.NOTICE(
            '\n  Desde otro dispositivo en la misma red, abri cualquiera de'
            '\n  las URLs "Red LAN" - celular, otra laptop, tablet.'
            '\n  Asegurate que tu .env permita la IP en ALLOWED_HOSTS.'
            '\n' + sep + '\n'
        ))
        call_command('runserver', f'0.0.0.0:{port}')

    def _red_activa_es_publica(self):
        """True si la red WiFi activa esta clasificada como Public.

        Windows clasifica algunas WiFis residenciales como Public por
        default. Las reglas de firewall comunes solo aplican a
        Domain/Private, asi que la red queda inaccesible.
        """
        import platform, subprocess
        if platform.system() != 'Windows':
            return False
        try:
            r = subprocess.run(
                ['powershell', '-NoProfile', '-Command',
                 "Get-NetConnectionProfile | Where-Object {$_.IPv4Connectivity -eq 'Internet'} | "
                 "Select-Object -ExpandProperty NetworkCategory"],
                capture_output=True, text=True, timeout=8,
            )
            if r.returncode != 0:
                return False
            return 'Public' in r.stdout
        except Exception:
            return False

    def _perfiles_regla_firewall(self, port: str):
        """Devuelve set de perfiles ('private', 'domain', 'public') que
        cubre la regla de firewall del puerto, o None si no se puede
        determinar."""
        import platform, subprocess
        if platform.system() != 'Windows':
            return None
        try:
            r = subprocess.run(
                ['netsh', 'advfirewall', 'firewall', 'show', 'rule', 'name=all'],
                capture_output=True, text=True, timeout=10,
            )
            if r.returncode != 0:
                return None
            # Buscar el bloque con LocalPort = nuestro puerto y leer Perfiles.
            bloques = r.stdout.split('Nombre de regla')
            perfiles = set()
            for b in bloques:
                if f'LocalPort:                            {port}' in b or \
                   f'Local Port:                           {port}' in b:
                    # Linea "Perfiles: ..." o "Profiles: ..."
                    for line in b.split('\n'):
                        L = line.strip().lower()
                        if L.startswith('perfiles:') or L.startswith('profiles:'):
                            valor = line.split(':', 1)[1].strip().lower()
                            for p in ('private', 'privada', 'domain', 'dominio', 'public', 'publica'):
                                if p in valor:
                                    # normalizar a ingles
                                    perfiles.add({
                                        'privada': 'private',
                                        'dominio': 'domain',
                                        'publica': 'public',
                                    }.get(p, p))
            return perfiles or None
        except Exception:
            return None

    def _regla_firewall_existe(self, port: str):
        """Best-effort: revisa si Windows Firewall tiene regla abriendo el
        puerto. Devuelve True/False/None (None si no podemos detectar)."""
        import platform, subprocess
        if platform.system() != 'Windows':
            return None
        try:
            r = subprocess.run(
                ['netsh', 'advfirewall', 'firewall', 'show', 'rule', 'name=all'],
                capture_output=True, text=True, timeout=10,
            )
            if r.returncode != 0:
                return None
            return f'LocalPort:                            {port}' in r.stdout \
                or f'Local Port:                           {port}' in r.stdout
        except Exception:
            return None
