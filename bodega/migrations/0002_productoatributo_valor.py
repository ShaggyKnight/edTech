# -*- coding: utf-8 -*-
# Generated by Django 1.11.1 on 2017-07-03 01:18
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('bodega', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='productoatributo',
            name='valor',
            field=models.CharField(blank=True, max_length=30, null=True),
        ),
    ]
