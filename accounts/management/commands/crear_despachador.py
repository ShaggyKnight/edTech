"""Crea (o actualiza) un usuario con rol DESPACHADOR.

Idempotente: si el usuario ya existe, solo se asegura de que tenga el
rol + is_staff + perfil con notificaciones activas. No pisa la password
de un usuario existente salvo que pases --password.

Uso:
    # Crear el despachador por defecto (username=despacho).
    python manage.py crear_despachador

    # Con datos propios.
    python manage.py crear_despachador --username juan \
        --email juan@ideasboutique.cl --nombre Juan --password secreto123

    # Resetear la password de uno existente.
    python manage.py crear_despachador --username despacho --password nueva123
"""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand
from django.db import transaction

from accounts.roles import DESPACHADOR


class Command(BaseCommand):
    help = 'Crea o actualiza un usuario con rol DESPACHADOR (idempotente).'

    def add_arguments(self, parser):
        parser.add_argument('--username', default='despacho')
        parser.add_argument('--email', default='despacho@ideasboutique.cl')
        parser.add_argument('--nombre', default='Despacho')
        parser.add_argument('--apellido', default='Ideas Boutique')
        parser.add_argument(
            '--password', default='',
            help='Si se omite y el usuario es NUEVO, se usa "despacho1234". '
                 'Si el usuario ya existe, sin --password no se toca su pass.',
        )

    @transaction.atomic
    def handle(self, *args, **opts):
        User = get_user_model()
        username = opts['username'].strip()

        grupo, _ = Group.objects.get_or_create(name=DESPACHADOR)

        user, created = User.objects.get_or_create(
            username=username,
            defaults={
                'email': opts['email'],
                'first_name': opts['nombre'],
                'last_name': opts['apellido'],
                'is_staff': True,   # necesario para entrar al backoffice
            },
        )

        if created:
            password = opts['password'] or 'despacho1234'
            user.set_password(password)
            user.is_staff = True
            user.save()
            self.stdout.write(self.style.SUCCESS(
                f'+ Usuario creado: {username} (password: {password})'
            ))
        else:
            # Asegurar is_staff aunque ya existiera.
            if not user.is_staff:
                user.is_staff = True
                user.save(update_fields=['is_staff'])
            if opts['password']:
                user.set_password(opts['password'])
                user.save()
                self.stdout.write(self.style.WARNING(
                    f'~ Password de {username} reseteada.'
                ))
            else:
                self.stdout.write(self.style.NOTICE(
                    f'= Usuario {username} ya existia (password sin cambios).'
                ))

        # Asignar el rol.
        if not user.groups.filter(name=DESPACHADOR).exists():
            user.groups.add(grupo)
            self.stdout.write(self.style.SUCCESS(
                f'+ Rol DESPACHADOR asignado a {username}.'
            ))

        # Garantizar el perfil con notificaciones activas. El signal
        # post_save crea el perfil para users nuevos, pero por si acaso
        # (users pre-existentes sin perfil) lo aseguramos aca.
        from accounts.models import PerfilUsuario
        perfil, _ = PerfilUsuario.objects.get_or_create(usuario=user)
        if not perfil.recibe_notif_ecommerce:
            perfil.recibe_notif_ecommerce = True
            perfil.save(update_fields=['recibe_notif_ecommerce'])

        self.stdout.write(self.style.SUCCESS(
            f'\nListo. {username} puede entrar en /cuenta/login/ y ver '
            f'la cola en /despacho/.'
        ))
