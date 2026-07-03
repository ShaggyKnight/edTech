"""Crea el rol OPERADOR — operación completa de la tienda, simplificada.

Pensado para la dueña: POS + ventas + despacho + stock + productos +
ofertas. Sin materiales, etiquetas, reportes financieros, admin Django
ni gestión de usuarios. Menos pantallas que admin, más que cajero.
"""
from django.apps import apps as django_apps
from django.contrib.auth.management import create_permissions
from django.db import migrations


def _asegurar_permisos_base(app_labels):
    for app_label in app_labels:
        app_config = django_apps.get_app_config(app_label)
        create_permissions(app_config, verbosity=0)


def crear_rol_operador(apps, schema_editor):
    from accounts.roles import OPERADOR, ROLE_PERMISSIONS

    _asegurar_permisos_base(['auth', 'contenttypes', 'catalogo', 'bodega', 'pos'])

    Group = apps.get_model('auth', 'Group')
    Permission = apps.get_model('auth', 'Permission')
    ContentType = apps.get_model('contenttypes', 'ContentType')

    grupo, _ = Group.objects.get_or_create(name=OPERADOR)

    permisos = []
    for app_label, models_map in ROLE_PERMISSIONS[OPERADOR].items():
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


def eliminar_rol_operador(apps, schema_editor):
    Group = apps.get_model('auth', 'Group')
    Group.objects.filter(name='operador').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0005_rol_despachador'),
    ]

    operations = [
        migrations.RunPython(crear_rol_operador, eliminar_rol_operador),
    ]
