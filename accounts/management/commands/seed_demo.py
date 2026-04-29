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
    Colegio,
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
        parser.add_argument(
            '--reset-passwords', action='store_true',
            help='Reescribe las contraseñas de los usuarios demo a los valores '
                 'documentados (útil cuando perdés acceso o cambiaron los hashes).',
        )

    @transaction.atomic
    def handle(self, *args, **opts):
        if opts['reset']:
            self._reset()

        self.reset_passwords = opts.get('reset_passwords', False)
        self.now = timezone.now()
        self.stdout.write(self.style.NOTICE('Sembrando datos demo…'))

        admin = self._usuarios()
        tienda, bodega = self._tienda_y_bodega()
        familias = self._familias()
        colegios = self._colegios()
        atrs = self._atributos()
        productos = self._productos(familias, colegios, atrs)
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
        self.stdout.write('  Produccion:      http://127.0.0.1:8000/reportes/produccion/')
        self.stdout.write('  Caja:            http://127.0.0.1:8000/reportes/caja/')
        self.stdout.write('  Tienda online:   http://127.0.0.1:8000/tienda/')
        self.stdout.write('  Cliente demo:    cliente@demo.cl / demo12345')

        # Aviso para que /tienda/ no quede vacia: el .env tiene que apuntar
        # a "Ideas Boutique" (la tienda con stock real del seed). Si quedo
        # un seed viejo con otra tienda, la online se ve vacia aunque hay
        # productos sembrados.
        boutique = Tienda.objects.filter(nombre_organizacion='Ideas Boutique').first()
        from django.conf import settings as _s
        actual_pk = getattr(_s, 'ECOMMERCE_TIENDA_ID', None)
        if boutique and actual_pk != boutique.pk:
            self.stdout.write(self.style.WARNING(
                f'\n[!] Para que /tienda/ muestre productos: en tu .env pone '
                f'ECOMMERCE_TIENDA_ID={boutique.pk} (ahora = {actual_pk}).'
            ))

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
        if c or self.reset_passwords:
            admin.set_password('admin')
            admin.save()
        self._say('Superuser admin / admin', creado=c)

        # Cajero y bodeguero, sumados al grupo correspondiente.
        from django.contrib.auth.models import Group
        for username, password, rol in (
            ('cajera', 'demo12345', CAJERO),
            ('bodeguero', 'demo12345', BODEGUERO),
        ):
            user, c = User.objects.get_or_create(
                username=username, defaults={'is_staff': True},
            )
            if c or self.reset_passwords:
                user.set_password(password)
                user.save()
            grupo = Group.objects.filter(name=rol).first()
            if grupo:
                user.groups.add(grupo)
            self._say(f'Usuario {username} / {password} ({rol})', creado=c)

        # Cliente de la tienda online.
        cliente, c = User.objects.get_or_create(
            username='cliente@demo.cl',
            defaults={
                'email': 'cliente@demo.cl',
                'first_name': 'Carla', 'last_name': 'Soto',
            },
        )
        if c or self.reset_passwords:
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

    def _colegios(self):
        """4 colegios de la comuna que ya tienen productos en la tienda."""
        datos = [
            ('sfj',    'San Francisco Javier',  'Caupolicán 920, Los Vilos'),
            ('dp',     'Divina Providencia',    'Av. Caupolicán 1234, Los Vilos'),
            ('lohse',  'Nicolás F. Lohse',      'Av. Costanera 80, Los Vilos'),
            ('almagro','Diego de Almagro',      'Pasaje Almagro 230, Los Vilos'),
        ]
        out = {}
        for slug, nombre, direccion in datos:
            col, c = Colegio.objects.get_or_create(
                nombre=nombre,
                defaults={'direccion': direccion, 'activo': True},
            )
            out[slug] = col
            self._say(f'Colegio: {nombre}', creado=c)
        return out

    def _atributos(self):
        """Tres atributos: Talla (uniformes/moda), Volumen (perfumes), Concentración (perfumes)."""
        talla, _ = Atributo.objects.get_or_create(nombre='Talla')
        tallas = {}
        for t in ['XS', 'S', 'M', 'L', 'XL', 'XXL']:
            v, _ = ValorAtributo.objects.get_or_create(atributo=talla, valor=t)
            tallas[t] = v

        volumen, _ = Atributo.objects.get_or_create(nombre='Volumen')
        volumenes = {}
        for v_str, orden in [('5 ml', 1), ('30 ml', 2), ('50 ml', 3),
                             ('100 ml', 4), ('200 ml', 5)]:
            obj, _ = ValorAtributo.objects.get_or_create(
                atributo=volumen, valor=v_str, defaults={'orden': orden},
            )
            volumenes[v_str] = obj

        concentracion, _ = Atributo.objects.get_or_create(nombre='Concentración')
        concentraciones = {}
        for c_str, orden in [
            ('Cologne', 1), ('Eau de Toilette', 2),
            ('Eau de Parfum', 3), ('Elixir', 4),
        ]:
            obj, _ = ValorAtributo.objects.get_or_create(
                atributo=concentracion, valor=c_str, defaults={'orden': orden},
            )
            concentraciones[c_str] = obj

        return {
            'talla': talla, 'tallas': tallas,
            'volumen': volumen, 'volumenes': volumenes,
            'concentracion': concentracion, 'concentraciones': concentraciones,
        }

    def _productos(self, fam, colegios, atrs):
        out = {}
        unif = fam['Uniformes Escolares']
        sfj = colegios['sfj']
        dp = colegios['dp']
        lohse = colegios['lohse']
        almagro = colegios['almagro']

        # --- Uniformes San Francisco Javier ---
        # Compatibilidad: si quedó del seed anterior un "Buzo San Francisco
        # Javier" que ahora reemplazamos, lo renombramos en lugar de crear
        # uno nuevo (preserva variantes/stock/movimientos previos).
        viejo = Producto.objects.filter(nombre='Buzo San Francisco Javier').first()
        if viejo:
            viejo.nombre = 'Buzo SFJ Completo'
            viejo.colegio = sfj
            viejo.save()

        # Descripciones con los textos reales del negocio (palabras de Blanca,
        # abril 2026): tela mandada hacer especialmente, durabilidad, cuellos
        # confeccionados a tono, lana que no hace pelotitas, etc.
        DESC_BUZO_GENERAL = (
            'Buzo escolar oficial SFJ. Tela franela color silvia hecha '
            'especialmente para el colegio: semi-elástica para dar libertad '
            'de movimiento, no se mancha con agua y es muy duradera — tan '
            'durable que las familias suelen heredarlo entre hermanos. '
            'Confección con costuras firmes que no se abren. Bordado con '
            'insignia oficial.'
        )

        out['buzo_sfj_completo'] = self._producto_con_tallas(
            familia=unif, colegio=sfj, nombre='Buzo SFJ Completo',
            descripcion=DESC_BUZO_GENERAL + ' Set completo: pantalón + chaqueta.',
            precio_base=Decimal('38990'), precio_costo=Decimal('15000'),
            sku_prefix='BZSFJ-CMP', tallas=['XS', 'S', 'M', 'L', 'XL', 'XXL'], atrs=atrs,
        )
        out['buzo_sfj_pantalon'] = self._producto_con_tallas(
            familia=unif, colegio=sfj, nombre='Buzo SFJ Pantalón',
            descripcion=DESC_BUZO_GENERAL + ' Pieza individual: pantalón.',
            precio_base=Decimal('21990'), precio_costo=Decimal('9000'),
            sku_prefix='BZSFJ-PAN', tallas=['XS', 'S', 'M', 'L', 'XL', 'XXL'], atrs=atrs,
        )
        out['buzo_sfj_chaqueta'] = self._producto_con_tallas(
            familia=unif, colegio=sfj, nombre='Buzo SFJ Chaqueta',
            descripcion=DESC_BUZO_GENERAL + ' Pieza individual: chaqueta con cierre.',
            precio_base=Decimal('22990'), precio_costo=Decimal('9500'),
            sku_prefix='BZSFJ-CHQ', tallas=['XS', 'S', 'M', 'L', 'XL', 'XXL'], atrs=atrs,
        )
        out['polera_pique_sfj'] = self._producto_con_tallas(
            familia=unif, colegio=sfj, nombre='Polera piqué SFJ',
            descripcion=(
                'Polera piqué oficial SFJ, gris perla. Tejida en algodón con '
                'un pequeño porcentaje de fibra que evita la deformación con '
                'el uso. Los cuellos se confeccionan junto con la tela del '
                'cuerpo, así que el tono es exactamente el mismo (no esa '
                'diferencia que se nota cuando son cuellos comprados aparte). '
                'Bordado con insignia SFJ.'
            ),
            precio_base=Decimal('12990'), precio_costo=Decimal('5000'),
            sku_prefix='PQSFJ', tallas=['XS', 'S', 'M', 'L', 'XL'], atrs=atrs,
        )

        # Renombre histórico: "Falda escocesa SFJ" → tela real es Casimir Garib.
        falda_vieja = Producto.objects.filter(nombre='Falda escocesa SFJ').first()
        if falda_vieja:
            falda_vieja.nombre = 'Falda Casimir Garib SFJ'
            falda_vieja.save(update_fields=['nombre', 'modificado'])

        out['falda_sfj'] = self._producto_con_tallas(
            familia=unif, colegio=sfj, nombre='Falda Casimir Garib SFJ',
            descripcion=(
                'Falda escolar oficial SFJ en tela Casimir Garib color rojizo '
                'con cuadrillé. El Casimir Garib tiende a no arrugarse: '
                'mantiene la forma después de cada lavado y no se ve como '
                'trapo viejo con el uso. Largo escolar.'
            ),
            precio_base=Decimal('19990'), precio_costo=Decimal('8000'),
            sku_prefix='FLSFJ', tallas=['S', 'M', 'L', 'XL'], atrs=atrs,
        )
        out['chaleco_sfj'] = self._producto_con_tallas(
            familia=unif, colegio=sfj, nombre='Chaleco SFJ',
            descripcion=(
                'Chaleco oficial SFJ confeccionado a medida. Lana de buena '
                'calidad color rojo italiano que NO hace pelotitas en las '
                'mangas ni en el cuerpo y no se deforma con el uso. Bordado '
                'con insignia oficial.'
            ),
            precio_base=Decimal('24990'), precio_costo=Decimal('11000'),
            sku_prefix='CHSFJ', tallas=['XS', 'S', 'M', 'L', 'XL'], atrs=atrs,
        )

        # --- Uniformes otros colegios (DP, Lohse, Almagro) ---
        # Misma calidad de tela piqué, distintas insignias bordadas. Cada
        # colegio tiene su variante de cuello/puños propia.
        DESC_POLERA_OTRO = (
            'Polera piqué oficial confeccionada con tela 100% algodón con un '
            'porcentaje de fibra para que no se deforme. Cuellos del mismo '
            'tono que el cuerpo. Bordado con la insignia del colegio.'
        )

        out['polera_dp'] = self._producto_con_tallas(
            familia=unif, colegio=dp, nombre='Polera piqué Divina Providencia',
            descripcion=DESC_POLERA_OTRO,
            precio_base=Decimal('11990'), precio_costo=Decimal('4800'),
            sku_prefix='PQDP', tallas=['XS', 'S', 'M', 'L', 'XL'], atrs=atrs,
        )

        out['polera_lohse'] = self._producto_con_tallas(
            familia=unif, colegio=lohse, nombre='Polera piqué Nicolás F. Lohse',
            descripcion=DESC_POLERA_OTRO,
            precio_base=Decimal('11990'), precio_costo=Decimal('4800'),
            sku_prefix='PQLHS', tallas=['XS', 'S', 'M', 'L', 'XL'], atrs=atrs,
        )

        out['polera_almagro'] = self._producto_con_tallas(
            familia=unif, colegio=almagro, nombre='Polera piqué Diego de Almagro',
            descripcion=DESC_POLERA_OTRO,
            precio_base=Decimal('11990'), precio_costo=Decimal('4800'),
            sku_prefix='PQDA', tallas=['XS', 'S', 'M', 'L', 'XL'], atrs=atrs,
        )

        # --- Perfumes con atributos volumen + concentración ---
        out['yara'] = self._producto_perfume(
            familia=fam['Perfumes'], nombre='Lattafa Yara',
            descripcion='Notas dulces orientales (vainilla, ámbar, rosa).',
            precio_base=Decimal('29990'), precio_costo=Decimal('11000'),
            sku_prefix='YARA',
            variantes=[
                ('5 ml',   'Eau de Parfum',   Decimal('4990')),
                ('30 ml',  'Eau de Parfum',   Decimal('19990')),
                ('100 ml', 'Eau de Parfum',   Decimal('29990')),
            ],
            atrs=atrs,
        )
        out['oud'] = self._producto_perfume(
            familia=fam['Fragancias premium'], nombre='Oud Royal Elixir',
            descripcion='Edición especial. Madera de oud, especias, intensidad alta.',
            precio_base=Decimal('64990'), precio_costo=Decimal('25000'),
            sku_prefix='OUD',
            variantes=[
                ('30 ml',  'Elixir',          Decimal('44990')),
                ('100 ml', 'Elixir',          Decimal('64990')),
            ],
            atrs=atrs,
        )
        out['floral_clasico'] = self._producto_perfume(
            familia=fam['Perfumes'], nombre='Floral Clásico',
            descripcion='Fragancia floral suave para uso diario.',
            precio_base=Decimal('18990'), precio_costo=Decimal('7500'),
            sku_prefix='FLO',
            variantes=[
                ('50 ml',  'Eau de Toilette', Decimal('14990')),
                ('100 ml', 'Eau de Toilette', Decimal('18990')),
                ('100 ml', 'Eau de Parfum',   Decimal('22990')),
            ],
            atrs=atrs,
        )

        # --- Moda con variantes ---
        out['polera_basica'] = self._producto_con_tallas(
            familia=fam['Moda'], colegio=None, nombre='Polera básica unisex',
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
                              precio_costo, sku_prefix, tallas, atrs, colegio=None):
        p, c = Producto.objects.get_or_create(
            nombre=nombre,
            defaults={
                'familia': familia, 'colegio': colegio,
                'descripcion': descripcion,
                'precio_base': precio_base, 'precio_costo': precio_costo,
                'tiene_variantes': True, 'activo': True,
            },
        )
        # Si ya existía, actualizamos colegio/familia/descripción para que el
        # seed sea fuente de verdad — si cambiás los textos acá y re-corrés,
        # la DB queda al día sin tener que tocar admin Django.
        if not c:
            cambios = []
            if p.colegio_id != (colegio.pk if colegio else None):
                p.colegio = colegio
                cambios.append('colegio')
            if p.familia_id != familia.pk:
                p.familia = familia
                cambios.append('familia')
            if p.descripcion != descripcion:
                p.descripcion = descripcion
                cambios.append('descripcion')
            if cambios:
                cambios.append('modificado')
                p.save(update_fields=cambios)
        variantes = []
        for t in tallas:
            v, _ = ProductoVariante.objects.get_or_create(
                producto=p, sku=f'{sku_prefix}-{t}',
            )
            v.valores.add(atrs['tallas'][t])
            variantes.append(v)
        self._say(f'Producto: {nombre} ({len(variantes)} variantes)', creado=c)
        return {'producto': p, 'variantes': variantes}

    def _producto_perfume(self, *, familia, nombre, descripcion, precio_base,
                          precio_costo, sku_prefix, variantes, atrs):
        """Crea un perfume con variantes (volumen + concentración).

        `variantes`: lista de tuplas (volumen_str, concentracion_str, precio).
        Cada tupla genera una variante con SKU = `<prefix>-<vol_clean>-<conc_clean>`.
        """
        p, c = Producto.objects.get_or_create(
            nombre=nombre,
            defaults={
                'familia': familia, 'descripcion': descripcion,
                'precio_base': precio_base, 'precio_costo': precio_costo,
                'tiene_variantes': True, 'activo': True,
            },
        )
        var_objs = []
        for vol_str, conc_str, precio_v in variantes:
            vol_clean = vol_str.replace(' ', '').upper()
            conc_clean = ''.join(w[0] for w in conc_str.split()).upper()  # EdT, EdP, ELX
            sku = f'{sku_prefix}-{vol_clean}-{conc_clean}'
            v, _ = ProductoVariante.objects.get_or_create(
                producto=p, sku=sku,
                defaults={'precio_override': precio_v},
            )
            v.valores.add(atrs['volumenes'][vol_str], atrs['concentraciones'][conc_str])
            var_objs.append(v)
        self._say(f'Perfume: {nombre} ({len(var_objs)} variantes)', creado=c)
        return {'producto': p, 'variantes': var_objs}

    def _ofertas(self, productos):
        Oferta.objects.get_or_create(
            producto=productos['oud']['producto'],
            nombre='10% Oud Royal Elixir',
            defaults={
                'canal': Oferta.CANAL_AMBOS,
                'tipo': Oferta.TIPO_PORCENTAJE,
                'valor': Decimal('10'),
                'fecha_inicio': self.now - timedelta(days=2),
                'fecha_fin': self.now + timedelta(days=14),
                'activa': True,
            },
        )
        self._say('Oferta vigente: 10% en Oud Royal Elixir')

    def _stock_inicial(self, tienda, productos):
        # Calzón sin variantes.
        StockTienda.objects.get_or_create(
            tienda=tienda, producto=productos['calzon']['producto'],
            defaults={'cantidad': 30},
        )
        # Perfumes con variantes: stock por variante (botellas + decants).
        for key, cantidad in (('yara', 12), ('oud', 5), ('floral_clasico', 18)):
            for v in productos[key]['variantes']:
                StockTienda.objects.get_or_create(
                    tienda=tienda, variante=v,
                    defaults={'cantidad': cantidad},
                )
        # Polera básica (Moda) con stock por talla.
        for v in productos['polera_basica']['variantes']:
            StockTienda.objects.get_or_create(
                tienda=tienda, variante=v, defaults={'cantidad': 12},
            )
        # Poleras de otros colegios (DP, Lohse, Almagro): unas pocas por talla
        # como existencias iniciales (los SFJ los recibimos del taller).
        for key in ('polera_dp', 'polera_lohse', 'polera_almagro'):
            for v in productos[key]['variantes']:
                StockTienda.objects.get_or_create(
                    tienda=tienda, variante=v, defaults={'cantidad': 8},
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
        """Telas reales que se compran para confección.

        - Buzos SFJ: tela franela color silvia (gris medio).
        - Chalecos SFJ invierno: tela polar color negro.
        - Poleras SFJ + DP + Lohse + Almagro: tela piqué (gris perla SFJ).
        - Faldas SFJ: tela escocesa (rojizo cuadrillé).
        """
        out = {}

        # Migración del nombre viejo si existe.
        viejo = Material.objects.filter(nombre='Tela polar buzo SFJ').first()
        if viejo:
            viejo.nombre = 'Tela polar negra (chalecos SFJ)'
            viejo.descripcion = 'Polar negro para chalecos SFJ de invierno. Bordado con insignia.'
            viejo.save(update_fields=['nombre', 'descripcion'])

        # Idem para la falda: el nombre real de la tela es Casimir Garib.
        viejo_falda = Material.objects.filter(nombre='Tela escocesa SFJ').first()
        if viejo_falda:
            viejo_falda.nombre = 'Tela Casimir Garib SFJ'
            viejo_falda.descripcion = (
                'Casimir Garib color rojizo con cuadrillé para faldas SFJ. '
                'No se arruga, mantiene la forma después de cada lavado.'
            )
            viejo_falda.save(update_fields=['nombre', 'descripcion'])

        out['tela_polar_chaleco'], c1 = Material.objects.get_or_create(
            nombre='Tela polar negra (chalecos SFJ)',
            defaults={
                'descripcion': 'Polar negro para chalecos SFJ de invierno. Bordado con insignia.',
                'proveedor': proveedor,
                'costo_unitario_referencia': Decimal('42000'),
            },
        )
        out['tela_franela_buzo'], c2 = Material.objects.get_or_create(
            nombre='Tela franela silvia (buzos SFJ)',
            defaults={
                'descripcion': 'Franela color silvia (gris medio brillante) para pantalón y chaqueta de buzo SFJ.',
                'proveedor': proveedor,
                'costo_unitario_referencia': Decimal('38000'),
            },
        )
        out['tela_pique'], c3 = Material.objects.get_or_create(
            nombre='Tela piqué SFJ blanca',
            defaults={
                'descripcion': 'Piqué blanco gris perla para poleras SFJ.',
                'proveedor': proveedor,
                'costo_unitario_referencia': Decimal('35000'),
            },
        )
        out['tela_falda'], c4 = Material.objects.get_or_create(
            nombre='Tela Casimir Garib SFJ',
            defaults={
                'descripcion': (
                    'Casimir Garib color rojizo con cuadrillé para faldas SFJ. '
                    'No se arruga, mantiene la forma después de cada lavado.'
                ),
                'proveedor': proveedor,
                'costo_unitario_referencia': Decimal('38000'),
            },
        )
        for n, c in (
            ('Tela polar negra (chalecos SFJ)', c1),
            ('Tela franela silvia (buzos SFJ)', c2),
            ('Tela piqué SFJ', c3),
            ('Tela Casimir Garib SFJ', c4),
        ):
            self._say(f'Material: {n}', creado=c)
        return out

    def _rendimientos(self, materiales, productos, atrs):
        # Buzos SFJ (pantalón + chaqueta): franela color silvia.
        # Talla XL consume más tela → rinde menos por rollo.
        rinde_pant = {'XS': 80, 'S': 70, 'M': 65, 'L': 55, 'XL': 45, 'XXL': 38}
        rinde_chaq = {'XS': 70, 'S': 60, 'M': 55, 'L': 48, 'XL': 40, 'XXL': 34}
        for key, mapa in (
            ('buzo_sfj_pantalon', rinde_pant),
            ('buzo_sfj_chaqueta', rinde_chaq),
        ):
            for v in productos[key]['variantes']:
                talla = next((vl.valor for vl in v.valores.all()
                              if vl.atributo.nombre == 'Talla'), None)
                # Si tenía rendimiento con polar (seed viejo), lo borra
                # y lo crea con franela.
                Rendimiento.objects.filter(
                    variante=v, material=materiales['tela_polar_chaleco'],
                ).delete()
                Rendimiento.objects.update_or_create(
                    material=materiales['tela_franela_buzo'], variante=v,
                    defaults={'unidades_por_rollo': mapa.get(talla, 40)},
                )

        # Chalecos SFJ: polar negro. Tela más densa, rinden menos.
        rinde_chaleco = {'XS': 50, 'S': 45, 'M': 40, 'L': 36, 'XL': 32}
        for v in productos['chaleco_sfj']['variantes']:
            talla = next((vl.valor for vl in v.valores.all()
                          if vl.atributo.nombre == 'Talla'), None)
            Rendimiento.objects.update_or_create(
                material=materiales['tela_polar_chaleco'], variante=v,
                defaults={'unidades_por_rollo': rinde_chaleco.get(talla, 38)},
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

        # 1. Compras iniciales: 4 telas distintas para diferentes prendas.
        compras = [
            ('tela_franela_buzo',  5, Decimal('190000'), 'Franela silvia para buzos'),
            ('tela_polar_chaleco', 2, Decimal('84000'),  'Polar negro para chalecos invierno'),
            ('tela_pique',         4, Decimal('140000'), 'Piqué para poleras (SFJ + DP + Lohse + Almagro)'),
            ('tela_falda',         3, Decimal('114000'), 'Casimir Garib para faldas SFJ'),
        ]
        for key, qty, costo, descripcion in compras:
            comprar_material(
                material=materiales[key], bodega=bodega,
                cantidad=qty, costo_total=costo,
                tienda_caja=tienda,
                referencia=f'Compra inicial — {descripcion}',
                usuario=admin,
            )
        self._say(f'Compra inicial: {sum(q for _,q,_,_ in compras)} rollos en bodega + asientos de caja')

        # 2. Recepción de lote: 2 rollos de franela → pantalones M/L del buzo SFJ.
        def _por_talla(key, talla):
            for v in productos[key]['variantes']:
                if any(val.valor == talla for val in v.valores.all()
                       if val.atributo.nombre == 'Talla'):
                    return v
            raise ValueError(f'No se encontró variante {talla} en {key}')
        var_pant_m = _por_talla('buzo_sfj_pantalon', 'M')
        var_pant_l = _por_talla('buzo_sfj_pantalon', 'L')
        recibir_lote(
            material=materiales['tela_franela_buzo'], bodega=bodega,
            rollos_consumidos=2,
            lineas=[
                LineaProduccion(variante_id=var_pant_m.pk, cantidad=65),
                LineaProduccion(variante_id=var_pant_l.pk, cantidad=55),
            ],
            tienda=tienda,
            costo_confeccion=Decimal('276000'),  # confección + accesorios
            referencia='Lote pantalones SFJ — taller Don Mario, marzo 2026',
            usuario=admin,
        )
        self._say('Recepción de lote: 120 pantalones SFJ confeccionados + asiento')

    def _ventas_demo(self, tienda, productos):
        if ReciboVenta.objects.filter(payment_provider='mock').exists():
            self._say('Ventas demo', creado=False)
            return

        # Helpers de variante por talla / volumen-concentración.
        def _var_talla(key, talla):
            for v in productos[key]['variantes']:
                if any(val.valor == talla for val in v.valores.all()
                       if val.atributo.nombre == 'Talla'):
                    return v
            return productos[key]['variantes'][0]

        def _var_perfume(key, vol, conc):
            for v in productos[key]['variantes']:
                vols = [val.valor for val in v.valores.all() if val.atributo.nombre == 'Volumen']
                concs = [val.valor for val in v.valores.all() if val.atributo.nombre == 'Concentración']
                if vol in vols and conc in concs:
                    return v
            return productos[key]['variantes'][0]

        var_pant_m = _var_talla('buzo_sfj_pantalon', 'M')
        var_pant_l = _var_talla('buzo_sfj_pantalon', 'L')
        var_polera_m = _var_talla('polera_basica', 'M')
        var_yara_30 = _var_perfume('yara', '30 ml', 'Eau de Parfum')
        var_yara_5 = _var_perfume('yara', '5 ml', 'Eau de Parfum')
        var_oud_30 = _var_perfume('oud', '30 ml', 'Elixir')
        var_floral_50 = _var_perfume('floral_clasico', '50 ml', 'Eau de Toilette')

        ventas = [
            (ReciboVenta.CANAL_PRESENCIAL, Decimal('21990'), 0,
             'Sra. Rojas', [(var_pant_m, 1, Decimal('21990'))]),
            (ReciboVenta.CANAL_PRESENCIAL, Decimal('29980'), 1,
             'Cliente mostrador', [(var_floral_50, 2, Decimal('14990'))]),
            (ReciboVenta.CANAL_PRESENCIAL, Decimal('43980'), 2,
             'Sr. Pérez',
             [(var_pant_m, 1, Decimal('21990')),
              (var_pant_l, 1, Decimal('21990'))]),
            (ReciboVenta.CANAL_ONLINE, Decimal('40491'), 3,
             'Carla Soto', [(var_oud_30, 1, Decimal('40491'))]),
            (ReciboVenta.CANAL_ONLINE, Decimal('19960'), 4,
             'Pedro Soto', [(var_yara_5, 4, Decimal('4990'))]),
            (ReciboVenta.CANAL_ONLINE, Decimal('19990'), 6,
             'María Vidal', [(var_yara_30, 1, Decimal('19990'))]),
            (ReciboVenta.CANAL_ONLINE, Decimal('9990'), 7,
             'Ana Maldonado', [(var_polera_m, 1, Decimal('9990'))]),
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
