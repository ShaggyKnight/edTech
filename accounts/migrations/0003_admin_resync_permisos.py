"""Re-sincroniza al grupo `admin` con TODOS los permisos del sistema.

Por qué hace falta esto: la migración `0001_crear_roles` corrió cuando
las apps existentes eran solo `auth/contenttypes/catalogo/bodega/pos`.
En ese momento `Permission.objects.all()` no incluía aún los permisos
de `contabilidad`, `reportes`, ni `ecommerce` (esas apps se crearon
después). Resultado: el grupo `admin` quedó con un subset estancado
de permisos, y usuarios como `blanca` no veían el link de Reportes
porque la navbar lo gate-ea con `perms.contabilidad.view_movimientocaja`.

Esta migración es idempotente: corre `permissions.set(all)` cada vez
que se ejecuta migrate, así que cualquier app nueva queda cubierta sin
tener que crear otra migración.
"""

from django.apps import apps as django_apps
from django.contrib.auth.management import create_permissions
from django.db import migrations


def _asegurar_permisos_base(app_labels):
    for app_label in app_labels:
        try:
            app_config = django_apps.get_app_config(app_label)
        except LookupError:
            continue
        create_permissions(app_config, verbosity=0)


def resync_admin_permisos(apps, schema_editor):
    _asegurar_permisos_base([
        'auth', 'contenttypes', 'catalogo', 'bodega', 'pos',
        'contabilidad', 'reportes', 'ecommerce', 'accounts',
    ])

    Group = apps.get_model('auth', 'Group')
    Permission = apps.get_model('auth', 'Permission')

    try:
        admin_group = Group.objects.get(name='admin')
    except Group.DoesNotExist:
        # raro pero defensivo: si no existe, lo crea
        admin_group = Group.objects.create(name='admin')

    admin_group.permissions.set(Permission.objects.all())


def noop(apps, schema_editor):
    # No hay revert real — los permisos quedan asignados.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0002_permisos_colegio'),
        # Forzamos que esta corra DESPUES de que existan las apps que aportan
        # los content_types/permisos nuevos. Si alguna de estas dependencias
        # cambia de número, hay que actualizar acá.
        ('contabilidad', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(resync_admin_permisos, noop),
    ]
