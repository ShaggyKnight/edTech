# -*- coding: utf-8 -*-
# Generated by Django 1.11.1 on 2017-06-11 03:21
from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('bodega', '0002_auto_20170611_0317'),
    ]

    operations = [
        migrations.AlterField(
            model_name='productolinea',
            name='producto',
            field=models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, to='bodega.Producto'),
        ),
    ]