"""Aplica los nuevos permisos definidos en accounts.roles tras agregar
`catalogo.Colegio` (Fase N): bodeguero gana view_colegio, admin recibe
todos los permisos automáticamente.

Idempotente — si los permisos ya están aplicados, no hace nada.
"""
from django.apps import apps as django_apps
from django.contrib.auth.management import create_permissions
from django.db import migrations


def _asegurar_permisos_base(app_labels):
    for app_label in app_labels:
        app_config = django_apps.get_app_config(app_label)
        create_permissions(app_config, verbosity=0)


def reaplicar_permisos(apps, schema_editor):
    from accounts.roles import ADMIN, ROLE_PERMISSIONS

    _asegurar_permisos_base(['auth', 'contenttypes', 'catalogo', 'bodega', 'pos'])

    Group = apps.get_model('auth', 'Group')
    Permission = apps.get_model('auth', 'Permission')
    ContentType = apps.get_model('contenttypes', 'ContentType')

    # Admin = todos los permisos del sistema (incluye los nuevos de colegio).
    admin_group, _ = Group.objects.get_or_create(name=ADMIN)
    admin_group.permissions.set(Permission.objects.all())

    # Bodeguero: re-set de sus permisos según ROLE_PERMISSIONS actual.
    for rol_name, apps_map in ROLE_PERMISSIONS.items():
        group, _ = Group.objects.get_or_create(name=rol_name)
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
                        permisos.append(Permission.objects.get(
                            content_type=ct, codename=codename,
                        ))
                    except Permission.DoesNotExist:
                        continue
        group.permissions.set(permisos)


def vacio(apps, schema_editor):
    """No-op para reverse — los permisos quedan, no causan daño."""
    pass


class Migration(migrations.Migration):
    dependencies = [
        ('accounts', '0001_crear_roles'),
        ('catalogo', '0002_auto_20260428_2225'),
    ]
    operations = [
        migrations.RunPython(reaplicar_permisos, reverse_code=vacio),
    ]
