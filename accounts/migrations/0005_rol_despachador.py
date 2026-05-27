"""Crea el rol DESPACHADOR + asigna permisos + perfil para users existentes.

DESPACHADOR prepara y despacha pedidos online. Ve productos + stock (read)
y puede marcar recibos como despachados.
"""
from django.apps import apps as django_apps
from django.contrib.auth.management import create_permissions
from django.db import migrations


def _asegurar_permisos_base(app_labels):
    for app_label in app_labels:
        app_config = django_apps.get_app_config(app_label)
        create_permissions(app_config, verbosity=0)


def crear_rol_despachador(apps, schema_editor):
    from accounts.roles import DESPACHADOR, ROLE_PERMISSIONS

    _asegurar_permisos_base(['auth', 'contenttypes', 'catalogo', 'bodega', 'pos'])

    Group = apps.get_model('auth', 'Group')
    Permission = apps.get_model('auth', 'Permission')
    ContentType = apps.get_model('contenttypes', 'ContentType')

    grupo, _ = Group.objects.get_or_create(name=DESPACHADOR)

    permisos = []
    for app_label, models_map in ROLE_PERMISSIONS[DESPACHADOR].items():
        for model_name, actions in models_map.items():
            try:
                ct = ContentType.objects.get(app_label=app_label, model=model_name)
            except ContentType.DoesNotExist:
                continue
            for action in actions:
                codename = f'{action}_{model_name}'
                try:
                    permisos.append(Permission.objects.get(content_type=ct, codename=codename))
                except Permission.DoesNotExist:
                    continue
    grupo.permissions.set(permisos)


def crear_perfiles_para_users_existentes(apps, schema_editor):
    """El signal post_save crea perfiles para users nuevos, pero los
    users existentes (creados antes de esta migracion) no lo tienen.
    Backfill via raw queryset (no podemos usar el signal porque corre
    sobre el modelo real, no el historico)."""
    User = apps.get_model('auth', 'User')
    PerfilUsuario = apps.get_model('accounts', 'PerfilUsuario')

    for user in User.objects.all():
        PerfilUsuario.objects.get_or_create(usuario_id=user.pk)


def eliminar_rol_despachador(apps, schema_editor):
    Group = apps.get_model('auth', 'Group')
    Group.objects.filter(name='despachador').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0004_perfil_usuario'),
        ('auth', '0012_alter_user_first_name_max_length'),
        ('contenttypes', '0002_remove_content_type_name'),
    ]

    operations = [
        migrations.RunPython(crear_rol_despachador, eliminar_rol_despachador),
        # Backfill: perfiles para los users existentes (admin, cajeros, etc).
        migrations.RunPython(
            crear_perfiles_para_users_existentes,
            migrations.RunPython.noop,
        ),
    ]
