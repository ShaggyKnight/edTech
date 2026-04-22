from django.apps import apps as django_apps
from django.contrib.auth.management import create_permissions
from django.db import migrations


def _asegurar_permisos_base(app_labels):
    """Fuerza la creación de rows en auth_permission para las apps dadas.

    Los Permission los crea el signal post_migrate al final de `migrate`, pero
    esta migración necesita usarlos antes. Sin esto, asignar permisos a los
    Groups deja los grupos vacíos.
    """
    for app_label in app_labels:
        app_config = django_apps.get_app_config(app_label)
        create_permissions(app_config, verbosity=0)


def crear_grupos_y_permisos(apps, schema_editor):
    from accounts.roles import ADMIN, BODEGUERO, CAJERO, ROLE_PERMISSIONS

    _asegurar_permisos_base(['auth', 'contenttypes', 'bodega', 'tienda'])

    Group = apps.get_model('auth', 'Group')
    Permission = apps.get_model('auth', 'Permission')
    ContentType = apps.get_model('contenttypes', 'ContentType')

    for rol in (ADMIN, CAJERO, BODEGUERO):
        Group.objects.get_or_create(name=rol)

    admin_group = Group.objects.get(name=ADMIN)
    admin_group.permissions.set(Permission.objects.all())

    for rol_name, apps_map in ROLE_PERMISSIONS.items():
        group = Group.objects.get(name=rol_name)
        permisos = []
        for app_label, models_map in apps_map.items():
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
        group.permissions.set(permisos)


def eliminar_grupos(apps, schema_editor):
    Group = apps.get_model('auth', 'Group')
    Group.objects.filter(name__in=('admin', 'cajero', 'bodeguero')).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('auth', '0012_alter_user_first_name_max_length'),
        ('contenttypes', '0002_remove_content_type_name'),
        ('bodega', '0001_initial'),
        ('tienda', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(crear_grupos_y_permisos, eliminar_grupos),
    ]
