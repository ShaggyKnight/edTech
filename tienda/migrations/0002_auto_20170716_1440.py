# -*- coding: utf-8 -*-
# Generated by Django 1.11.1 on 2017-07-16 18:40
from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('bodega', '0004_auto_20170716_1439'),
        ('tienda', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='StockTienda',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('cantidad_contada', models.PositiveIntegerField(default=0)),
                ('producto', models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, to='bodega.Producto')),
            ],
        ),
        migrations.AddField(
            model_name='tienda',
            name='stock',
            field=models.ForeignKey(default=1, on_delete=django.db.models.deletion.CASCADE, to='tienda.StockTienda'),
            preserve_default=False,
        ),
    ]