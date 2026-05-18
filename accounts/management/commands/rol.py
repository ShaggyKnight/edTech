"""Verifica y asigna roles a usuarios.

Uso:
    python manage.py rol                          # lista todos los users + sus roles
    python manage.py rol <username>               # detalle de un usuario
    python manage.py rol <username> --set=admin   # asigna rol admin (saca otros roles)
    python manage.py rol <username> --add=cajero  # AGREGA rol sin sacar los otros
    python manage.py rol <username> --del=cajero  # solo saca ese rol

Roles validos: admin, cajero, bodeguero.

Nota: si el user es `is_superuser`, ya tiene TODOS los permisos sin
necesidad de estar en ningun grupo. Asignarle "admin" igual no hace
daño — Django toma el union de permisos.
"""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand, CommandError

from accounts.roles import ALL_ROLES


class Command(BaseCommand):
    help = 'Verifica o asigna roles (admin/cajero/bodeguero) a usuarios.'

    def add_arguments(self, parser):
        parser.add_argument(
            'username', nargs='?', default=None,
            help='Username a inspeccionar / modificar. Omitir para listar todos.',
        )
        parser.add_argument(
            '--set', dest='set_rol', default=None,
            help='Reemplaza los roles del usuario por este (saca los demás).',
        )
        parser.add_argument(
            '--add', dest='add_rol', default=None,
            help='Agrega este rol sin tocar los demás.',
        )
        parser.add_argument(
            '--del', dest='del_rol', default=None,
            help='Saca este rol del usuario.',
        )

    def handle(self, *args, **opts):
        User = get_user_model()
        username = opts['username']

        if not username:
            self._listar_todos(User)
            return

        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist:
            raise CommandError(f'Usuario "{username}" no existe.')

        # Modificaciones (en orden: set → add → del)
        if opts['set_rol']:
            self._validar_rol(opts['set_rol'])
            user.groups.clear()
            user.groups.add(Group.objects.get(name=opts['set_rol']))
            self.stdout.write(self.style.SUCCESS(
                f'OK: {username} ahora tiene SOLO el rol "{opts["set_rol"]}".'
            ))

        if opts['add_rol']:
            self._validar_rol(opts['add_rol'])
            user.groups.add(Group.objects.get(name=opts['add_rol']))
            self.stdout.write(self.style.SUCCESS(
                f'OK: rol "{opts["add_rol"]}" agregado a {username}.'
            ))

        if opts['del_rol']:
            self._validar_rol(opts['del_rol'])
            grupo = Group.objects.filter(name=opts['del_rol']).first()
            if grupo and grupo in user.groups.all():
                user.groups.remove(grupo)
                self.stdout.write(self.style.SUCCESS(
                    f'OK: rol "{opts["del_rol"]}" removido de {username}.'
                ))
            else:
                self.stdout.write(self.style.WARNING(
                    f'{username} no tenia el rol "{opts["del_rol"]}".'
                ))

        # Estado final
        self._detalle_usuario(user)

    def _validar_rol(self, rol):
        if rol not in ALL_ROLES:
            raise CommandError(
                f'Rol invalido: "{rol}". Validos: {", ".join(ALL_ROLES)}.'
            )

    def _detalle_usuario(self, user):
        sep = '-' * 60
        self.stdout.write('')
        self.stdout.write(sep)
        self.stdout.write(f'  Username:     {user.username}')
        self.stdout.write(f'  Email:        {user.email or "(vacio)"}')
        self.stdout.write(f'  is_active:    {user.is_active}')
        self.stdout.write(f'  is_staff:     {user.is_staff}')
        self.stdout.write(f'  is_superuser: {user.is_superuser}')
        roles = list(user.groups.values_list('name', flat=True))
        roles_relevantes = [r for r in roles if r in ALL_ROLES]
        self.stdout.write(f'  Roles:        {", ".join(roles_relevantes) or "(ninguno)"}')

        # Diagnostico de permisos por grupo. Util para detectar el caso
        # donde el grupo `admin` quedo con permisos viejos porque la
        # migracion 0001 corrio antes de que existieran apps como
        # `contabilidad` o `reportes`. Si los numeros no coinciden,
        # correr la migracion 0003_admin_resync_permisos.
        total_perms = Permission.objects.count()
        for rol_name in roles_relevantes:
            grupo = Group.objects.filter(name=rol_name).first()
            if grupo:
                count = grupo.permissions.count()
                if rol_name == 'admin' and count < total_perms:
                    self.stdout.write(self.style.WARNING(
                        f'  Perms grupo {rol_name}: {count}/{total_perms}  '
                        f'(ATENCION: faltan {total_perms - count}, '
                        f'corre `python manage.py migrate accounts`)'
                    ))
                else:
                    self.stdout.write(f'  Perms grupo {rol_name}: {count}')

        # Acceso esperado
        self.stdout.write('')
        self.stdout.write('  Que puede ver:')
        if user.is_superuser or 'admin' in roles_relevantes:
            self.stdout.write(self.style.SUCCESS('    [OK] /reportes/  (Dashboard, EERR, Balance, Caja, Produccion)'))
            self.stdout.write(self.style.SUCCESS('    [OK] /bodega/    (stock + CRUD productos / variantes / etc)'))
            self.stdout.write(self.style.SUCCESS('    [OK] /pos/       (POS presencial + ventas + recibos)'))
            self.stdout.write(self.style.SUCCESS('    [OK] /admin/     (Django admin completo)'))
        else:
            if 'cajero' in roles_relevantes:
                self.stdout.write(self.style.SUCCESS('    [OK] /pos/       (POS + sus ventas + recibos)'))
                self.stdout.write(self.style.SUCCESS('    [OK] /bodega/    (solo VER stock, sin editar)'))
            elif 'bodeguero' in roles_relevantes:
                self.stdout.write(self.style.SUCCESS('    [OK] /bodega/    (CRUD productos / variantes / materiales)'))
                self.stdout.write(self.style.NOTICE('    [--] /pos/       (NO)'))
            else:
                self.stdout.write(self.style.WARNING('    Sin rol staff. Cliente normal → solo /tienda/cuenta/'))
            self.stdout.write(self.style.NOTICE('    [--] /reportes/  (NO — requiere rol admin)'))
        self.stdout.write(sep)

    def _listar_todos(self, User):
        sep = '=' * 75
        self.stdout.write(sep)
        self.stdout.write(f'  {"USERNAME":<20} {"SUPER":<6} {"STAFF":<6} ROLES')
        self.stdout.write(sep)
        for u in User.objects.all().order_by('username'):
            roles = ', '.join(
                u.groups.filter(name__in=ALL_ROLES).values_list('name', flat=True)
            ) or '(ninguno)'
            su = 'SI' if u.is_superuser else ''
            st = 'SI' if u.is_staff else ''
            self.stdout.write(f'  {u.username:<20} {su:<6} {st:<6} {roles}')
        self.stdout.write(sep)
        self.stdout.write(
            '\nPara ver detalle:  python manage.py rol <username>'
            '\nPara asignar:      python manage.py rol <username> --set=admin'
        )
