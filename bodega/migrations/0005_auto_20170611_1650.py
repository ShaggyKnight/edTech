# -*- coding: utf-8 -*-
# Generated by Django 1.11.1 on 2017-06-11 16:50
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('bodega', '0004_remove_producto_nombre'),
    ]

    operations = [
        migrations.AlterField(
            model_name='productolinea',
            name='largo',
            field=models.PositiveIntegerField(default=0),
        ),
    ]