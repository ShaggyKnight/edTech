"""Seed con datos de prueba realistas para Ideas Boutique.

Idempotente: corrérselo varias veces no duplica datos.

Cubre todo el dominio:
  - Usuarios (admin, cajero, bodeguero, cliente).
  - Tienda + Bodega.
  - Catálogo: 4 familias (uniformes, perfumes, fragancias, moda, lencería),
    productos con/sin variantes, ofertas vigentes.
  - Stock terminado en tienda.
  - Materiales (rollos de tela), rendimientos por variante, stock en bodega.
  - 1 compra de tela y 1 recepción de lote ya procesadas (con asientos).
  - Ventas presenciales + online pagadas (para poblar dashboard).
  - 1 salida de caja manual (arriendo).

Uso:
    python manage.py seed_demo
    python manage.py seed_demo --reset   # elimina antes de crear (peligroso)
"""

from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from accounts.roles import BODEGUERO, CAJERO
from bodega.models import (
    Bodega,
    Material,
    MovimientoMaterial,
    Proveedor,
    Rendimiento,
    StockMaterial,
    StockTienda,
    Tienda,
)
from bodega.services import LineaProduccion, comprar_material, recibir_lote
from catalogo.models import (
    Atributo,
    Familia,
    Oferta,
    Producto,
    ProductoVariante,
    ValorAtributo,
)
from contabilidad.models import MovimientoCaja
from contabilidad.services import registrar_ingreso_venta, registrar_salida
from pos.models import ReciboVenta, ReciboVentaDetalle

User = get_user_model()


class Command(BaseCommand):
    help = 'Genera datos de prueba realistas para Ideas Boutique.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--reset', action='store_true',
            help='Borra recibos, asientos y movimientos antes de sembrar.',
        )

    @transaction.atomic
    def handle(self, *args, **opts):
        if opts['reset']:
            self._reset()

        self.now = timezone.now()
        self.stdout.write(self.style.NOTICE('Sembrando datos demo…'))

        admin = self._usuarios()
        tienda, bodega = self._tienda_y_bodega()
        familias = self._familias()
        atrs = self._atributos()
        productos = self._productos(familias, atrs)
        self._ofertas(productos)
        self._stock_inicial(tienda, productos)
        proveedor = self._proveedor()
        materiales = self._materiales(proveedor)
        self._rendimientos(materiales, productos, atrs)
        self._compras_y_lote(admin, tienda, bodega, materiales, productos, atrs)
        self._ventas_demo(tienda, productos)
        self._salida_arriendo(tienda, admin)

        self.stdout.write(self.style.SUCCESS('\nListo. Acceso:'))
        self.stdout.write('  Admin Django:    http://127.0.0.1:8000/admin/  (admin / admin)')
        self.stdout.write('  Reportes:        http://127.0.0.1:8000/reportes/')
        self.stdout.write('  Producción:      http://127.0.0.1:8000/reportes/produccion/')
        self.stdout.write('  Caja:            http://127.0.0.1:8000/reportes/caja/')
        self.stdout.write('  Tienda online:   http://127.0.0.1:8000/tienda/')
        self.stdout.write('  Cliente demo:    cliente@demo.cl / demo12345')

    # -------- helpers --------------------------------------------------------

    def _say(self, mensaje, creado=True):
        prefix = self.style.SUCCESS('[OK]  ') if creado else self.style.WARNING('[SKIP]')
        self.stdout.write(f'{prefix} {mensaje}')

    def _reset(self):
        from bodega.models import MovimientoStock
        ReciboVentaDetalle.objects.all().delete()
        ReciboVenta.objects.all().delete()
        MovimientoCaja.objects.all().delete()
        MovimientoMaterial.objects.all().delete()
        MovimientoStock.objects.all().delete()
        StockMaterial.objects.all().delete()
        StockTienda.objects.all().delete()
        Rendimiento.objects.all().delete()
        self.stdout.write(self.style.WARNING('Reset: recibos, asientos, movimientos y stock borrados.'))

    # -------- secciones ------------------------------------------------------

    def _usuarios(self):
        admin, c = User.objects.get_or_create(
            username='admin',
            defaults={'email': 'admin@ideas.local', 'is_staff': True, 'is_superuser': True},
        )
        if c:
            admin.set_password('admin')
            admin.save()
        self._say(f'Superuser admin/admin', creado=c)

        # Cajero y bodeguero, sumados al grupo correspondiente.
        from django.contrib.auth.models import Group
        for username, password, rol in (
            ('cajera', 'demo12345', CAJERO),
            ('bodeguero', 'demo12345', BODEGUERO),
        ):
            user, c = User.objects.get_or_create(
                username=username, defaults={'is_staff': True},
            )
            if c:
                user.set_password(password)
                user.save()
            grupo = Group.objects.filter(name=rol).first()
            if grupo:
                user.groups.add(grupo)
            self._say(f'Usuario {username}/{password} ({rol})', creado=c)

        # Cliente de la tienda online.
        cliente, c = User.objects.get_or_create(
            username='cliente@demo.cl',
            defaults={
                'email': 'cliente@demo.cl',
                'first_name': 'Carla', 'last_name': 'Soto',
            },
        )
        if c:
            cliente.set_password('demo12345')
            cliente.save()
        self._say('Cliente cliente@demo.cl / demo12345', creado=c)
        return admin

    def _tienda_y_bodega(self):
        tienda, c = Tienda.objects.get_or_create(
            nombre_organizacion='Ideas Boutique',
            defaults={
                'rut_organizacion': '76.111.111-1',
                'direccion': 'Caupolicán 437-B, Los Vilos',
                'telefono_contacto': '+56 9 5555 5555',
                'correo_contacto': 'ventas@ideas.cl',
                'activa': True,
            },
        )
        self._say(f'Tienda: {tienda.nombre_organizacion}', creado=c)

        bodega, c = Bodega.objects.get_or_create(
            nombre='Bodega Caupolicán',
            defaults={'tienda': tienda, 'ubicacion': 'Trastienda Caupolicán 437-B'},
        )
        self._say(f'Bodega: {bodega.nombre}', creado=c)
        return tienda, bodega

    def _familias(self):
        nombres = ['Uniformes Escolares', 'Perfumes', 'Fragancias premium', 'Moda', 'Lencería']
        out = {}
        for n in nombres:
            f, c = Familia.objects.get_or_create(nombre=n)
            out[n] = f
            self._say(f'Familia: {n}', creado=c)
        return out

    def _atributos(self):
        talla, _ = Atributo.objects.get_or_create(nombre='Talla')
        tallas = {}
        for t in ['XS', 'S', 'M', 'L', 'XL', 'XXL']:
            v, _ = ValorAtributo.objects.get_or_create(atributo=talla, valor=t)
            tallas[t] = v
        return {'talla': talla, 'tallas': tallas}

    def _productos(self, fam, atrs):
        out = {}

        # --- Uniformes con variantes por talla ---
        unif = fam['Uniformes Escolares']
        out['buzo_sfj'] = self._producto_con_tallas(
            familia=unif, nombre='Buzo San Francisco Javier',
            descripcion='Buzo escolar oficial del Colegio San Francisco Javier. Tela polar reforzada.',
            precio_base=Decimal('28990'), precio_costo=Decimal('11000'),
            sku_prefix='BZSFJ', tallas=['XS', 'S', 'M', 'L', 'XL', 'XXL'], atrs=atrs,
        )
        out['polera_pique_sfj'] = self._producto_con_tallas(
            familia=unif, nombre='Polera piqué SFJ',
            descripcion='Polera piqué blanca con bordado SFJ.',
            precio_base=Decimal('12990'), precio_costo=Decimal('5000'),
            sku_prefix='PQSFJ', tallas=['XS', 'S', 'M', 'L', 'XL'], atrs=atrs,
        )
        out['falda_sfj'] = self._producto_con_tallas(
            familia=unif, nombre='Falda escocesa SFJ',
            descripcion='Falda tartán oficial SFJ.',
            precio_base=Decimal('19990'), precio_costo=Decimal('8000'),
            sku_prefix='FLSFJ', tallas=['S', 'M', 'L', 'XL'], atrs=atrs,
        )

        # --- Perfumes (sin variantes) ---
        out['perfume_50'] = self._producto_simple(
            familia=fam['Perfumes'], nombre='Eau de Toilette Clásico 50ml',
            descripcion='Fragancia floral clásica.',
            precio_base=Decimal('18990'), precio_costo=Decimal('7500'),
        )
        out['decant_5'] = self._producto_simple(
            familia=fam['Perfumes'], nombre='Decant 5ml',
            descripcion='Decant para probar antes de la botella completa.',
            precio_base=Decimal('4990'), precio_costo=Decimal('1500'),
        )
        out['perfume_premium'] = self._producto_simple(
            familia=fam['Fragancias premium'], nombre='Perfume premium 100ml',
            descripcion='Edición especial. Notas amaderadas.',
            precio_base=Decimal('48990'), precio_costo=Decimal('20000'),
        )

        # --- Moda con variantes ---
        out['polera_basica'] = self._producto_con_tallas(
            familia=fam['Moda'], nombre='Polera básica unisex',
            descripcion='Polera de algodón 100%, corte recto.',
            precio_base=Decimal('9990'), precio_costo=Decimal('3500'),
            sku_prefix='PB', tallas=['S', 'M', 'L', 'XL'], atrs=atrs,
        )

        # --- Lencería simple ---
        out['calzon'] = self._producto_simple(
            familia=fam['Lencería'], nombre='Calzón básico algodón',
            descripcion='Pack 3 unidades.',
            precio_base=Decimal('6990'), precio_costo=Decimal('2500'),
        )

        return out

    def _producto_simple(self, *, familia, nombre, descripcion, precio_base, precio_costo):
        p, c = Producto.objects.get_or_create(
            nombre=nombre,
            defaults={
                'familia': familia, 'descripcion': descripcion,
                'precio_base': precio_base, 'precio_costo': precio_costo,
                'tiene_variantes': False, 'activo': True,
            },
        )
        self._say(f'Producto: {nombre}', creado=c)
        return {'producto': p, 'variantes': []}

    def _producto_con_tallas(self, *, familia, nombre, descripcion, precio_base,
                              precio_costo, sku_prefix, tallas, atrs):
        p, c = Producto.objects.get_or_create(
            nombre=nombre,
            defaults={
                'familia': familia, 'descripcion': descripcion,
                'precio_base': precio_base, 'precio_costo': precio_costo,
                'tiene_variantes': True, 'activo': True,
            },
        )
        variantes = []
        for t in tallas:
            v, _ = ProductoVariante.objects.get_or_create(
                producto=p, sku=f'{sku_prefix}-{t}',
            )
            v.valores.add(atrs['tallas'][t])
            variantes.append(v)
        self._say(f'Producto: {nombre} ({len(variantes)} variantes)', creado=c)
        return {'producto': p, 'variantes': variantes}

    def _ofertas(self, productos):
        Oferta.objects.get_or_create(
            producto=productos['perfume_premium']['producto'],
            nombre='10% perfume premium',
            defaults={
                'canal': Oferta.CANAL_AMBOS,
                'tipo': Oferta.TIPO_PORCENTAJE,
                'valor': Decimal('10'),
                'fecha_inicio': self.now - timedelta(days=2),
                'fecha_fin': self.now + timedelta(days=14),
                'activa': True,
            },
        )
        self._say('Oferta vigente: 10% en perfume premium')

    def _stock_inicial(self, tienda, productos):
        # Stock para lo terminado (los uniformes los modelaremos producidos en lote).
        for p in (productos['perfume_50'], productos['decant_5'], productos['perfume_premium'],
                  productos['calzon']):
            StockTienda.objects.get_or_create(
                tienda=tienda, producto=p['producto'],
                defaults={'cantidad': 30},
            )
        # Polera básica (Moda) con stock por talla.
        for v in productos['polera_basica']['variantes']:
            StockTienda.objects.get_or_create(
                tienda=tienda, variante=v, defaults={'cantidad': 12},
            )
        self._say('Stock inicial sembrado en tienda')

    def _proveedor(self):
        prov, c = Proveedor.objects.get_or_create(
            nombre_proveedor='Textil del Sur',
            defaults={
                'rut_proveedor': '77.999.888-K',
                'direccion': 'Av. Industrial 1200, Santiago',
                'telefono': '+56 2 2555 0001',
                'correo': 'ventas@textildelsur.cl',
                'nombre_contacto': 'Marta Henríquez',
            },
        )
        self._say(f'Proveedor: {prov.nombre_proveedor}', creado=c)
        return prov

    def _materiales(self, proveedor):
        out = {}
        out['tela_buzo'], c1 = Material.objects.get_or_create(
            nombre='Tela polar buzo SFJ',
            defaults={
                'descripcion': 'Polar reforzado azul marino oficial SFJ.',
                'proveedor': proveedor,
                'costo_unitario_referencia': Decimal('42000'),
            },
        )
        out['tela_pique'], c2 = Material.objects.get_or_create(
            nombre='Tela piqué SFJ blanca',
            defaults={
                'descripcion': 'Piqué blanco para poleras SFJ.',
                'proveedor': proveedor,
                'costo_unitario_referencia': Decimal('35000'),
            },
        )
        out['tela_falda'], c3 = Material.objects.get_or_create(
            nombre='Tela escocesa SFJ',
            defaults={
                'descripcion': 'Tartán para faldas SFJ.',
                'proveedor': proveedor,
                'costo_unitario_referencia': Decimal('38000'),
            },
        )
        for n, c in (('Tela polar buzo SFJ', c1), ('Tela piqué SFJ', c2), ('Tela escocesa SFJ', c3)):
            self._say(f'Material: {n}', creado=c)
        return out

    def _rendimientos(self, materiales, productos, atrs):
        # Buzos: la talla XL consume más tela, así que rinden menos.
        rinde_buzo = {'XS': 60, 'S': 55, 'M': 50, 'L': 42, 'XL': 35, 'XXL': 30}
        for v in productos['buzo_sfj']['variantes']:
            talla = v.valores.first().valor
            Rendimiento.objects.get_or_create(
                material=materiales['tela_buzo'], variante=v,
                defaults={'unidades_por_rollo': rinde_buzo.get(talla, 40)},
            )

        # Poleras piqué SFJ: rinden más unidades por rollo (tela más liviana).
        rinde_polera = {'XS': 90, 'S': 80, 'M': 70, 'L': 60, 'XL': 50}
        for v in productos['polera_pique_sfj']['variantes']:
            talla = v.valores.first().valor
            Rendimiento.objects.get_or_create(
                material=materiales['tela_pique'], variante=v,
                defaults={'unidades_por_rollo': rinde_polera.get(talla, 65)},
            )

        # Faldas SFJ.
        rinde_falda = {'S': 45, 'M': 40, 'L': 35, 'XL': 30}
        for v in productos['falda_sfj']['variantes']:
            talla = v.valores.first().valor
            Rendimiento.objects.get_or_create(
                material=materiales['tela_falda'], variante=v,
                defaults={'unidades_por_rollo': rinde_falda.get(talla, 35)},
            )
        self._say('Rendimientos (BOM) por variante sembrados')

    def _compras_y_lote(self, admin, tienda, bodega, materiales, productos, atrs):
        # Si ya hay movimientos de material, asumimos que todo el flujo está sembrado.
        if MovimientoMaterial.objects.exists():
            self._say('Movimientos de material', creado=False)
            return

        # 1. Compra inicial de los 3 tipos de tela (5 + 4 + 3 rollos).
        comprar_material(
            material=materiales['tela_buzo'], bodega=bodega,
            cantidad=5, costo_total=Decimal('220000'),
            tienda_caja=tienda, referencia='Factura 2024-008',
            usuario=admin,
        )
        comprar_material(
            material=materiales['tela_pique'], bodega=bodega,
            cantidad=4, costo_total=Decimal('148000'),
            tienda_caja=tienda, referencia='Factura 2024-008',
            usuario=admin,
        )
        comprar_material(
            material=materiales['tela_falda'], bodega=bodega,
            cantidad=3, costo_total=Decimal('120000'),
            tienda_caja=tienda, referencia='Factura 2024-008',
            usuario=admin,
        )
        self._say('Compra inicial: 12 rollos en bodega + asientos de caja')

        # 2. Una recepción de lote: usamos 2 rollos de tela buzo y recibimos prendas.
        # Variantes M (50/rollo) y L (42/rollo) → consumimos 1 rollo de cada.
        var_m = next(v for v in productos['buzo_sfj']['variantes']
                     if v.valores.first().valor == 'M')
        var_l = next(v for v in productos['buzo_sfj']['variantes']
                     if v.valores.first().valor == 'L')
        recibir_lote(
            material=materiales['tela_buzo'], bodega=bodega,
            rollos_consumidos=2,
            lineas=[
                LineaProduccion(variante_id=var_m.pk, cantidad=50),
                LineaProduccion(variante_id=var_l.pk, cantidad=42),
            ],
            tienda=tienda,
            costo_confeccion=Decimal('276000'),  # confección + accesorios
            referencia='Lote A — taller Don Mario, marzo 2026',
            usuario=admin,
        )
        self._say('Recepción de lote: 92 buzos confeccionados + asiento')

    def _ventas_demo(self, tienda, productos):
        if ReciboVenta.objects.filter(payment_provider='mock').exists():
            self._say('Ventas demo', creado=False)
            return

        var_buzo_m = next(v for v in productos['buzo_sfj']['variantes']
                          if v.valores.first().valor == 'M')
        var_buzo_l = next(v for v in productos['buzo_sfj']['variantes']
                          if v.valores.first().valor == 'L')
        var_polera_m = productos['polera_basica']['variantes'][1]

        ventas = [
            (ReciboVenta.CANAL_PRESENCIAL, Decimal('28990'), 0,
             'Sra. Rojas', [(var_buzo_m, 1, Decimal('28990'))]),
            (ReciboVenta.CANAL_PRESENCIAL, Decimal('37980'), 1,
             'Cliente mostrador', [(productos['perfume_50']['producto'], 2, Decimal('18990'))]),
            (ReciboVenta.CANAL_PRESENCIAL, Decimal('57980'), 2,
             'Sr. Pérez',
             [(var_buzo_m, 1, Decimal('28990')),
              (var_buzo_l, 1, Decimal('28990'))]),
            (ReciboVenta.CANAL_ONLINE, Decimal('44091'), 3,
             'Carla Soto',
             [(productos['perfume_premium']['producto'], 1, Decimal('44091'))]),
            (ReciboVenta.CANAL_ONLINE, Decimal('19980'), 4,
             'Pedro Soto',
             [(productos['decant_5']['producto'], 4, Decimal('4990'))]),
            (ReciboVenta.CANAL_ONLINE, Decimal('9990'), 6,
             'María Vidal', [(var_polera_m, 1, Decimal('9990'))]),
        ]

        for canal, total, dias, cliente, items in ventas:
            recibo = ReciboVenta.objects.create(
                canal=canal, tienda=tienda,
                subtotal=total, descuento=Decimal('0'), total=total,
                estado=ReciboVenta.ESTADO_PAGADO,
                payment_provider='mock', payment_reference=f'mock-{cliente[:6]}-{dias}',
                cliente_nombre=cliente,
                cliente_email='cliente@demo.cl' if canal == ReciboVenta.CANAL_ONLINE else '',
            )
            for prod, cant, precio in items:
                kwargs = {
                    'recibo': recibo, 'cantidad': cant,
                    'precio_unitario': precio, 'descuento': Decimal('0'),
                }
                if isinstance(prod, ProductoVariante):
                    kwargs['variante'] = prod
                    kwargs['descripcion'] = f'{prod.producto.nombre} [{prod.sku}]'
                else:
                    kwargs['producto'] = prod
                    kwargs['descripcion'] = prod.nombre
                ReciboVentaDetalle.objects.create(**kwargs)
            if dias:
                ReciboVenta.objects.filter(pk=recibo.pk).update(
                    creado=self.now - timedelta(days=dias),
                )
                recibo.refresh_from_db()
            registrar_ingreso_venta(recibo)
        self._say(f'{len(ventas)} ventas pagadas + asientos de caja')

    def _salida_arriendo(self, tienda, admin):
        if MovimientoCaja.objects.filter(
            tipo=MovimientoCaja.SALIDA, concepto__icontains='Arriendo',
        ).exists():
            self._say('Arriendo abril', creado=False)
            return
        registrar_salida(
            tienda=tienda, monto=Decimal('450000'),
            concepto='Arriendo local Caupolicán abril', usuario=admin,
        )
        self._say('Salida de caja: arriendo $450.000')
