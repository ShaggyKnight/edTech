# -*- coding: utf-8 -*-
# Generated by Django 1.11.1 on 2017-07-16 18:39
from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('bodega', '0003_auto_20170702_2123'),
    ]

    operations = [
        migrations.CreateModel(
            name='HistoriaVentas',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('fecha_venta', models.DateTimeField(auto_now_add=True)),
            ],
        ),
        migrations.CreateModel(
            name='ReciboVenta',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('fecha_hora_venta', models.DateTimeField(auto_now_add=True)),
                ('usuario_vendedor', models.IntegerField(blank=True, null=True)),
            ],
        ),
        migrations.CreateModel(
            name='ReciboVentaDetalle',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('cantidad_vendida', models.PositiveIntegerField()),
                ('precio_calculado', models.PositiveIntegerField()),
                ('id_producto', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='bodega.Producto')),
                ('id_reciboVenta', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='tienda.ReciboVenta')),
            ],
        ),
        migrations.CreateModel(
            name='Tienda',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('nombre_organizacion', models.CharField(max_length=200, unique=True)),
                ('direccion', models.CharField(blank=True, max_length=200, null=True)),
                ('telefono_contacto', models.PositiveIntegerField()),
                ('correo_contacto', models.EmailField(max_length=254)),
                ('rut_organizacion', models.CharField(max_length=20)),
            ],
        ),
        migrations.AddField(
            model_name='reciboventa',
            name='tienda',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='tienda.Tienda'),
        ),
        migrations.AddField(
            model_name='historiaventas',
            name='id_reciboVenta',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='tienda.ReciboVenta'),
        ),
    ]