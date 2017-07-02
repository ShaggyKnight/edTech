# -*- coding: utf-8 -*-
# Generated by Django 1.11.1 on 2017-06-21 03:07
from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='Bodega',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('nombre', models.CharField(max_length=30, unique=True)),
                ('ubicacion', models.TextField(max_length=30)),
            ],
        ),
        migrations.CreateModel(
            name='Familia',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('nombre', models.CharField(max_length=30, unique=True)),
                ('fecha', models.DateTimeField(auto_now=True)),
            ],
        ),
        migrations.CreateModel(
            name='Inventario',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('fecha_inventario', models.DateTimeField(verbose_name='fecha inventario')),
                ('bodega', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='bodega.Bodega')),
            ],
        ),
        migrations.CreateModel(
            name='Inventariolinea',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('cantidad_contada', models.IntegerField(default=0)),
                ('observacion', models.CharField(max_length=200)),
                ('inventario', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='bodega.Inventario')),
            ],
        ),
        migrations.CreateModel(
            name='Material',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('nombre', models.CharField(max_length=30)),
                ('descripcion', models.CharField(max_length=200)),
                ('precio', models.FloatField(default=0)),
                ('precio_provedor', models.PositiveIntegerField(default=0)),
                ('largo', models.PositiveIntegerField(blank=True, default=0, null=True)),
                ('comerciable', models.BooleanField()),
                ('bodega', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='bodega.Bodega')),
            ],
        ),
        migrations.CreateModel(
            name='Producto',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('nombre', models.CharField(max_length=200, unique=True)),
                ('precio', models.FloatField(default=0)),
                ('talla', models.CharField(choices=[('S', 'Small'), ('M', 'Medium'), ('L', 'Large')], max_length=1)),
                ('familia', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='bodega.Familia')),
            ],
        ),
        migrations.AddField(
            model_name='material',
            name='mat_producto',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='bodega.Producto'),
        ),
        migrations.AddField(
            model_name='inventariolinea',
            name='producto',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='bodega.Producto'),
        ),
    ]
