# -*- coding: utf-8 -*-
# Generated by Django 1.11.1 on 2017-07-16 18:39
from __future__ import unicode_literals

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('bodega', '0003_auto_20170702_2123'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='stocktienda',
            name='producto',
        ),
        migrations.DeleteModel(
            name='StockTienda',
        ),
    ]
