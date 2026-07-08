"""Re-sincroniza el grupo despachador: SOLO la pantalla de despacho.

Antes tenia view_stocktienda y view_reciboventa, que hacian aparecer las
secciones "Stock" y "Ventas" en el sidebar. La duena lo quiere puro
despacho, asi que reducimos sus permisos a lo minimo (ver roles.py).
El acceso a /despacho/ es por ROL, no por permisos, asi que no se rompe.
"""
from django.apps import apps as django_apps
from django.contrib.auth.management import create_permissions
from django.db import migrations


def _asegurar_permisos_base(app_labels):
    for app_label in app_labels:
        app_config = django_apps.get_app_config(app_label)
        create_permissions(app_config, verbosity=0)


def resync_despachador(apps, schema_editor):
    from accounts.roles import DESPACHADOR, ROLE_PERMISSIONS

    _asegurar_permisos_base(['auth', 'contenttypes', 'catalogo', 'bodega', 'pos'])

    Group = apps.get_model('auth', 'Group')
    Permission = apps.get_model('auth', 'Permission')
    ContentType = apps.get_model('contenttypes', 'ContentType')

    try:
        grupo = Group.objects.get(name=DESPACHADOR)
    except Group.DoesNotExist:
        return  # aun no existe (fresh DB): la 0005 ya lo crea con estos perms

    permisos = []
    for app_label, models_map in ROLE_PERMISSIONS[DESPACHADOR].items():
        for model_name, actions in models_map.items():
            try:
                ct = ContentType.objects.get(app_label=app_label, model=model_name)
            except ContentType.DoesNotExist:
                continue
            for action in actions:
                try:
                    permisos.append(Permission.objects.get(
                        content_type=ct, codename=f'{action}_{model_name}'))
                except Permission.DoesNotExist:
                    continue
    # set() reemplaza el set completo — saca los permisos viejos.
    grupo.permissions.set(permisos)


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0006_rol_operador'),
    ]

    operations = [
        migrations.RunPython(resync_despachador, migrations.RunPython.noop),
    ]
