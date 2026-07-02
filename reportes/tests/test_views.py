"""Smoke tests de las vistas de reportes.

- Un usuario no admin es rebotado.
- Un superuser ve el dashboard con los números correctos.
- La vista de caja permite registrar una salida.
"""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from bodega.models import Tienda
from contabilidad.models import MovimientoCaja
from contabilidad.services import registrar_ingreso_venta, registrar_salida
from pos.models import ReciboVenta

User = get_user_model()


class DashboardAccesoTests(TestCase):
    def test_anonimo_redirige_a_login(self):
        resp = self.client.get(reverse('reportes:dashboard'))
        self.assertEqual(resp.status_code, 302)

    def test_usuario_sin_rol_recibe_redirect_o_forbidden(self):
        User.objects.create_user('juan', password='x')
        self.client.login(username='juan', password='x')
        resp = self.client.get(reverse('reportes:dashboard'))
        # user_passes_test sin rol admin redirige al login.
        self.assertEqual(resp.status_code, 302)


class DashboardContenidoTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser('ana', 'a@a.cl', 'x')
        cls.tienda = Tienda.objects.create(nombre_organizacion='Central', activa=True)
        # Una venta pagada presencial → debe aparecer + asiento de caja.
        recibo = ReciboVenta.objects.create(
            canal=ReciboVenta.CANAL_PRESENCIAL,
            tienda=cls.tienda,
            subtotal=Decimal('10000'), descuento=Decimal('0'), total=Decimal('10000'),
            estado=ReciboVenta.ESTADO_PAGADO,
        )
        registrar_ingreso_venta(recibo)

    def test_admin_ve_dashboard_con_totales(self):
        self.client.login(username='ana', password='x')
        resp = self.client.get(reverse('reportes:dashboard'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Dashboard')
        # BUG-005: el monto va formateado en CLP (con separador de miles).
        # py3.9/dj4.2 local usa NBSP como separador → normalizar.
        body = resp.content.decode().replace('\xa0', '.')
        self.assertIn('$10.000', body)  # total de ventas / promedio
        self.assertIn('Central', body)  # tienda en el selector

    def test_request_normal_devuelve_pagina_completa(self):
        """GET sin HX-Request: pagina completa con <html>, head, form, etc."""
        self.client.login(username='ana', password='x')
        resp = self.client.get(reverse('reportes:dashboard'))
        body = resp.content.decode()
        self.assertIn('<!DOCTYPE html>', body)
        self.assertIn('id="dashboard-content"', body)
        self.assertIn('<select name="dias"', body)
        # Charts JS embebido (define renderDashboardCharts).
        self.assertIn('renderDashboardCharts', body)

    def test_request_htmx_devuelve_solo_partial(self):
        """GET con HX-Request: solo el partial, NO el shell."""
        self.client.login(username='ana', password='x')
        resp = self.client.get(
            reverse('reportes:dashboard') + '?dias=7',
            HTTP_HX_REQUEST='true',
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        # Partial NO debe traer doctype ni <html> ni el form de filtros.
        self.assertNotIn('<!DOCTYPE html>', body)
        self.assertNotIn('<select name="dias"', body)
        # PERO debe traer el contenido dinamico.
        self.assertIn('Ventas totales', body)
        self.assertIn('Top productos vendidos', body)
        # Y el script inline que re-renderea los charts post-swap.
        self.assertIn('renderDashboardCharts', body)
        # Y el bloque OOB que actualiza el header con el periodo nuevo.
        self.assertIn('hx-swap-oob="true"', body)
        self.assertIn('Últimos 7 días corridos', body)

    def test_form_de_filtros_no_tiene_boton_actualizar(self):
        """Mejora: el boton "Actualizar" se quito — los filtros disparan
        HTMX al `change`. Queda solo dentro de <noscript> para fallback."""
        self.client.login(username='ana', password='x')
        resp = self.client.get(reverse('reportes:dashboard'))
        body = resp.content.decode()
        # Hay HTMX en el form.
        self.assertIn('hx-trigger="change from:select"', body)
        self.assertIn('hx-target="#dashboard-content"', body)
        # El boton "Actualizar" SOLO existe dentro de <noscript> (fallback).
        noscript_open = body.find('<noscript>')
        noscript_close = body.find('</noscript>')
        self.assertGreater(noscript_open, 0, '<noscript> debe existir')
        boton_pos = body.find('Actualizar')
        self.assertTrue(
            noscript_open < boton_pos < noscript_close,
            'El boton "Actualizar" debe estar dentro de <noscript>, '
            'no en el flujo normal del form.'
        )


class DashboardMejorasTests(TestCase):
    """Tests de las 3 mejoras del dashboard:
       #1 Comparativa vs período anterior — chip con % de variación.
       #2 Drill-down en KPIs — cada card es <a> al detalle.
       #3 Filtro por canal — `?canal=presencial|online`.
    """

    @classmethod
    def setUpTestData(cls):
        from datetime import timedelta
        from django.utils import timezone
        cls.admin = User.objects.create_superuser('eva', 'e@e.cl', 'x')
        cls.tienda = Tienda.objects.create(nombre_organizacion='Central', activa=True)

        ahora = timezone.now()
        # 2 ventas PRESENCIALES en los últimos 30 días.
        for monto in [10000, 20000]:
            r = ReciboVenta.objects.create(
                canal=ReciboVenta.CANAL_PRESENCIAL, tienda=cls.tienda,
                subtotal=monto, descuento=0, total=monto,
                estado=ReciboVenta.ESTADO_PAGADO,
            )
            registrar_ingreso_venta(r)
        # 1 venta ONLINE en los últimos 30 días.
        r_online = ReciboVenta.objects.create(
            canal=ReciboVenta.CANAL_ONLINE, tienda=cls.tienda,
            subtotal=15000, descuento=0, total=15000,
            estado=ReciboVenta.ESTADO_PAGADO,
        )
        registrar_ingreso_venta(r_online)

        # 1 venta presencial en el PERÍODO ANTERIOR (~45 días atrás)
        # para que la comparativa muestre algo no-trivial.
        r_prev = ReciboVenta.objects.create(
            canal=ReciboVenta.CANAL_PRESENCIAL, tienda=cls.tienda,
            subtotal=5000, descuento=0, total=5000,
            estado=ReciboVenta.ESTADO_PAGADO,
        )
        r_prev.creado = ahora - timedelta(days=45)
        r_prev.save(update_fields=['creado'])
        # Re-llamamos registrar_ingreso_venta solo después de actualizar
        # `creado`. Como ya hay un MovimientoCaja del save inicial,
        # ajustamos su fecha para que coincida con la venta vieja.
        from contabilidad.models import MovimientoCaja as MC
        mc = MC.objects.filter(recibo_venta=r_prev).first()
        if mc:
            mc.fecha = ahora - timedelta(days=45)
            mc.save(update_fields=['fecha'])

    def setUp(self):
        self.client.login(username='eva', password='x')

    # ─── #1 Comparativa vs período anterior ───────────────────────────

    def test_dashboard_renderiza_chips_de_variacion(self):
        resp = self.client.get(reverse('reportes:dashboard'))
        body = resp.content.decode()
        # Tiene que aparecer al menos un chip de variación.
        self.assertIn('variacion-chip', body,
            'Debe haber chip de variación vs período anterior bajo las KPIs.')

    def test_resumen_negocio_devuelve_anterior_si_se_pide(self):
        from reportes.services import resumen_negocio, ventana_por_defecto
        desde, hasta = ventana_por_defecto(30)
        r = resumen_negocio(
            tienda=self.tienda, desde=desde, hasta=hasta,
            incluir_anterior=True,
        )
        self.assertIsNotNone(r.anterior)
        # 1 venta en el periodo anterior con total 5000.
        self.assertEqual(r.anterior['n_ventas'], 1)
        self.assertEqual(int(r.anterior['total_ventas']), 5000)
        # var_total = ((45000 - 5000) / 5000) * 100 = 800%
        self.assertEqual(r.anterior['var_total'], 800)

    def test_variacion_pct_helper(self):
        from reportes.services import variacion_pct
        from decimal import Decimal
        self.assertEqual(variacion_pct(Decimal('120'), Decimal('100')), 20)
        self.assertEqual(variacion_pct(Decimal('80'),  Decimal('100')), -20)
        self.assertEqual(variacion_pct(Decimal('100'), Decimal('100')), 0)
        self.assertIsNone(variacion_pct(Decimal('0'),  Decimal('0')))
        self.assertIsNone(variacion_pct(Decimal('50'), Decimal('0')))

    # ─── #2 Drill-down en KPI cards ───────────────────────────────────

    def test_kpi_cards_son_links_clickeables(self):
        resp = self.client.get(reverse('reportes:dashboard'))
        body = resp.content.decode()
        self.assertIn('class="bo-card bo-kpi is-primary kpi-link"', body)
        # Y los hrefs apuntan a destinos válidos.
        from django.urls import reverse as rev
        self.assertIn(rev('pos:ventas'), body)
        self.assertIn(rev('reportes:caja'), body)
        self.assertIn(rev('bodega:stock'), body)

    def test_kpi_link_lleva_los_filtros_actuales(self):
        resp = self.client.get(
            reverse('reportes:dashboard') + f'?tienda={self.tienda.pk}&canal=online',
        )
        body = resp.content.decode()
        # El link de "Ventas totales" debe incluir desde/hasta + canal + tienda.
        self.assertIn('canal=online', body)
        self.assertIn(f'tienda={self.tienda.pk}', body)

    # ─── #3 Filtro de canal ───────────────────────────────────────────

    def test_filtro_canal_select_aparece_en_form(self):
        resp = self.client.get(reverse('reportes:dashboard'))
        body = resp.content.decode()
        self.assertIn('<select name="canal"', body)
        self.assertIn('>Presencial</option>', body)
        self.assertIn('>Online</option>', body)

    def test_filtro_canal_presencial_excluye_online(self):
        resp = self.client.get(
            reverse('reportes:dashboard') + '?canal=presencial',
        )
        ctx = resp.context
        # Total filtrado por canal: solo presenciales (10k + 20k = 30k).
        self.assertEqual(int(ctx['resumen'].total_ventas), 30000)
        self.assertEqual(ctx['resumen'].ventas_por_canal['online']['total'], 0)

    def test_filtro_canal_online_excluye_presencial(self):
        resp = self.client.get(
            reverse('reportes:dashboard') + '?canal=online',
        )
        ctx = resp.context
        # Solo la venta online de 15k.
        self.assertEqual(int(ctx['resumen'].total_ventas), 15000)
        self.assertEqual(ctx['resumen'].ventas_por_canal['presencial']['total'], 0)

    def test_canal_invalido_se_ignora(self):
        """Un canal espurio (`?canal=xxx`) NO debe romper — se trata
        como None (sin filtro)."""
        resp = self.client.get(
            reverse('reportes:dashboard') + '?canal=hackear',
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(resp.context['canal_filtro'])
        # Trae todas las ventas (3 ventas, 45000 total).
        self.assertEqual(int(resp.context['resumen'].total_ventas), 45000)


class EerrHtmxTests(TestCase):
    """Mismo patron que dashboard: filtros auto-submit via HTMX y la
    pagina no se recarga. View detecta `request.htmx` y devuelve solo
    el partial del contenido (`_eerr_content.html`)."""

    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser('eri', 'eri@e.cl', 'x')
        cls.tienda = Tienda.objects.create(nombre_organizacion='Central', activa=True)

    def setUp(self):
        self.client.login(username='eri', password='x')

    def test_request_normal_devuelve_pagina_completa(self):
        resp = self.client.get(reverse('reportes:eerr'))
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn('<!DOCTYPE html>', body)
        self.assertIn('id="eerr-content"', body)
        # El form tiene atributos HTMX.
        self.assertIn('hx-target="#eerr-content"', body)
        self.assertIn('hx-trigger="change from:select', body)
        # JS de re-render del chart definido en el shell.
        self.assertIn('renderEerrChart', body)

    def test_request_htmx_devuelve_solo_partial(self):
        resp = self.client.get(
            reverse('reportes:eerr'),
            HTTP_HX_REQUEST='true',
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        # Partial: sin DOCTYPE, sin form de filtros, sin chart script.
        self.assertNotIn('<!DOCTYPE html>', body)
        self.assertNotIn('<select name="periodo"', body)
        # Pero SI con el contenido dinámico.
        self.assertIn('Estado de Resultados — detalle', body)
        self.assertIn('Margen bruto', body)
        # OOB swap del header.
        self.assertIn('hx-swap-oob="true"', body)
        self.assertIn('id="eerr-periodo-info"', body)
        # Script inline que re-renderea el chart.
        self.assertIn('renderEerrChart', body)

    def test_form_no_tiene_boton_aplicar_fuera_de_noscript(self):
        """Mejora: el boton "Aplicar" se quito — los filtros disparan
        HTMX al `change`. Queda dentro de <noscript> para fallback."""
        resp = self.client.get(reverse('reportes:eerr'))
        body = resp.content.decode()
        noscript_open = body.find('<noscript>')
        noscript_close = body.find('</noscript>', noscript_open)
        self.assertGreater(noscript_open, 0)
        boton_pos = body.find('>Aplicar<')
        self.assertTrue(
            noscript_open < boton_pos < noscript_close,
            'El boton "Aplicar" debe estar dentro de <noscript>.'
        )

    def test_filtros_pasan_via_querystring(self):
        """Cambiar el modo a 'anio' filtra correctamente."""
        resp = self.client.get(
            reverse('reportes:eerr') + '?periodo=anio&anio=2026'
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['periodo']['modo'], 'anio')
        self.assertEqual(resp.context['periodo']['anio'], 2026)


class EerrMejorasTests(TestCase):
    """Tests de las 3 mejoras del EERR:
       #1 Comparativa vs período anterior — chip bajo cada KPI.
       #3 Atajos rápidos de período — chips clickeables arriba del form.
       #6 Desglose por familia — tabla con margen por línea de negocio.
    """

    @classmethod
    def setUpTestData(cls):
        from decimal import Decimal as D
        from catalogo.models import Familia, Producto
        cls.admin = User.objects.create_superuser('mar', 'm@m.cl', 'x')
        cls.tienda = Tienda.objects.create(nombre_organizacion='Central', activa=True)

        # 2 familias con productos. Voy a vender de las dos en el período
        # actual para probar el desglose.
        cls.fam_perf = Familia.objects.create(nombre='Perfumes')
        cls.fam_unif = Familia.objects.create(nombre='Uniformes')
        cls.prod_perf = Producto.objects.create(
            familia=cls.fam_perf, nombre='Yara EDP',
            precio_base=D('20000'), precio_costo=D('10000'),
            tiene_variantes=False,
        )
        cls.prod_unif = Producto.objects.create(
            familia=cls.fam_unif, nombre='Buzo escolar',
            precio_base=D('30000'), precio_costo=D('15000'),
            tiene_variantes=False,
        )

        # 1 venta de perfume (ingreso 20k, cogs 10k → margen 10k = 50%)
        from pos.models import ReciboVentaDetalle
        r1 = ReciboVenta.objects.create(
            canal=ReciboVenta.CANAL_PRESENCIAL, tienda=cls.tienda,
            subtotal=D('20000'), descuento=D('0'), total=D('20000'),
            estado=ReciboVenta.ESTADO_PAGADO,
        )
        ReciboVentaDetalle.objects.create(
            recibo=r1, producto=cls.prod_perf,
            descripcion='Yara EDP', cantidad=1,
            precio_unitario=D('20000'), descuento=D('0'),
        )
        registrar_ingreso_venta(r1)

        # 1 venta de uniforme (ingreso 30k, cogs 15k → margen 15k = 50%)
        r2 = ReciboVenta.objects.create(
            canal=ReciboVenta.CANAL_PRESENCIAL, tienda=cls.tienda,
            subtotal=D('30000'), descuento=D('0'), total=D('30000'),
            estado=ReciboVenta.ESTADO_PAGADO,
        )
        ReciboVentaDetalle.objects.create(
            recibo=r2, producto=cls.prod_unif,
            descripcion='Buzo escolar', cantidad=1,
            precio_unitario=D('30000'), descuento=D('0'),
        )
        registrar_ingreso_venta(r2)

    def setUp(self):
        self.client.login(username='mar', password='x')

    # ─── #1 Comparativa vs periodo anterior ───────────────────────────

    def test_eerr_anterior_se_calcula(self):
        """La view popula `eerr_anterior` con todas las metricas."""
        resp = self.client.get(reverse('reportes:eerr'))
        self.assertEqual(resp.status_code, 200)
        prev = resp.context['eerr_anterior']
        for key in (
            'ingresos', 'costo_ventas', 'margen_bruto', 'margen_pct',
            'utilidad_neta', 'var_ingresos', 'var_cogs',
            'var_margen_bruto', 'delta_margen_pct_ppts', 'var_utilidad_neta',
        ):
            self.assertIn(key, prev, f'eerr_anterior debe incluir "{key}"')

    def test_chips_variacion_aparecen_en_html(self):
        """Al menos un chip de variacion debe estar en el HTML."""
        resp = self.client.get(reverse('reportes:eerr'))
        body = resp.content.decode()
        # variacion-chip class is reused from the dashboard improvement.
        self.assertIn('variacion-chip', body)

    # ─── #3 Atajos rapidos de periodo ────────────────────────────────

    def test_atajos_renderizan_chips(self):
        resp = self.client.get(reverse('reportes:eerr'))
        body = resp.content.decode()
        self.assertIn('class="eerr-atajos"', body)
        # 5 atajos predefinidos.
        for label in ('Este mes', 'Mes anterior', 'Este año',
                      'Año anterior', 'Últimos 12 meses'):
            self.assertIn(label, body)
        # Y cada chip es link HTMX.
        self.assertIn('hx-target="#eerr-content"', body)

    def test_atajo_este_mes_esta_activo_por_default(self):
        """Default del EERR es el mes actual → el chip 'Este mes' debe
        estar activo (clase `eerr-chip-active`)."""
        resp = self.client.get(reverse('reportes:eerr'))
        body = resp.content.decode()
        # Buscar el chip activo y que sea el de "Este mes".
        active_idx = body.find('eerr-chip-active')
        self.assertGreater(active_idx, 0)
        # Texto "Este mes" debe aparecer cerca del chip activo
        # (el chip contiene mucho HTML — hx-get, hx-target, etc — antes
        # del label, asi que la ventana tiene que ser amplia).
        seccion = body[active_idx:active_idx + 600]
        self.assertIn('Este mes', seccion)

    # ─── #6 Desglose por familia ──────────────────────────────────────

    def test_eerr_incluye_desglose_por_familia(self):
        from reportes.services import ventana_por_defecto
        from contabilidad.services import estado_resultados
        desde, hasta = ventana_por_defecto(60)
        eerr_dato = estado_resultados(desde=desde, hasta=hasta, tienda=self.tienda)
        familias = {f['familia']: f for f in eerr_dato.desglose_por_familia}
        self.assertIn('Perfumes', familias)
        self.assertIn('Uniformes', familias)
        # Perfumes: 1 unidad, 20k ingreso, 10k cogs → margen 10k (50%).
        self.assertEqual(familias['Perfumes']['n_lineas'], 1)
        self.assertEqual(int(familias['Perfumes']['ingresos']), 20000)
        self.assertEqual(int(familias['Perfumes']['cogs']), 10000)
        self.assertEqual(int(familias['Perfumes']['margen']), 10000)
        # Ordenado por margen desc: Uniformes (15k) antes que Perfumes (10k).
        self.assertEqual(eerr_dato.desglose_por_familia[0]['familia'], 'Uniformes')
        self.assertEqual(eerr_dato.desglose_por_familia[1]['familia'], 'Perfumes')

    def test_desglose_familia_se_renderiza_en_template(self):
        resp = self.client.get(reverse('reportes:eerr'))
        body = resp.content.decode()
        self.assertIn('Desglose por línea de negocio', body)
        # Las 2 familias deben aparecer en el HTML.
        self.assertIn('Perfumes', body)
        self.assertIn('Uniformes', body)


class CajaViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser('ana', 'a@a.cl', 'x')
        cls.tienda = Tienda.objects.create(nombre_organizacion='Central', activa=True)

    def test_registrar_salida_manual(self):
        self.client.login(username='ana', password='x')
        resp = self.client.post(reverse('reportes:caja'), {
            'tienda': self.tienda.pk,
            'categoria': MovimientoCaja.GASTO_OPERATIVO,
            'monto': '50000',
            'concepto': 'Arriendo abril',
        }, follow=True)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(MovimientoCaja.objects.filter(
            tipo=MovimientoCaja.SALIDA, monto=Decimal('50000'),
            concepto='Arriendo abril',
            categoria=MovimientoCaja.GASTO_OPERATIVO,
        ).exists())

    def test_registrar_compra_inventario(self):
        """Una compra de telas / perfumes debe quedar como
        `costo_inventario`, no como gasto operativo — es ACTIVO contable,
        no gasto del periodo. Este test cubre el bug que existia cuando
        el form forzaba siempre `gasto_operativo`."""
        self.client.login(username='ana', password='x')
        self.client.post(reverse('reportes:caja'), {
            'tienda': self.tienda.pk,
            'categoria': MovimientoCaja.COSTO_INVENTARIO,
            'monto': '200000',
            'concepto': 'Compra de tela polar para buzos',
        })
        m = MovimientoCaja.objects.get(concepto='Compra de tela polar para buzos')
        self.assertEqual(m.categoria, MovimientoCaja.COSTO_INVENTARIO)
        self.assertEqual(m.tipo, MovimientoCaja.SALIDA)

    def test_registrar_pago_confeccion(self):
        """Pago a quien cose debe ir como `costo_produccion`, NO como
        gasto operativo. Tambien es ACTIVO contable."""
        self.client.login(username='ana', password='x')
        self.client.post(reverse('reportes:caja'), {
            'tienda': self.tienda.pk,
            'categoria': MovimientoCaja.COSTO_PRODUCCION,
            'monto': '150000',
            'concepto': 'Pago confección 20 buzos SFJ',
        })
        m = MovimientoCaja.objects.get(concepto='Pago confección 20 buzos SFJ')
        self.assertEqual(m.categoria, MovimientoCaja.COSTO_PRODUCCION)

    def test_form_initial_categoria_es_gasto_operativo(self):
        """El form arranca con `gasto_operativo` pre-seleccionado en
        el dropdown (caso mas comun). Este test confirma el initial,
        no el comportamiento sin data — un POST sin `categoria` falla
        porque el field es required."""
        from reportes.forms import CajaSalidaForm
        form = CajaSalidaForm()
        self.assertEqual(
            form.fields['categoria'].initial, MovimientoCaja.GASTO_OPERATIVO,
        )

    def test_form_categoria_es_requerido(self):
        """POST sin `categoria` falla — obliga al admin a elegir
        conscientemente como contabilizar el egreso."""
        from reportes.forms import CajaSalidaForm
        form = CajaSalidaForm(data={
            'tienda': self.tienda.pk,
            'monto': '50000',
            'concepto': 'Arriendo',
        })
        self.assertFalse(form.is_valid())
        self.assertIn('categoria', form.errors)

    def test_form_rechaza_categoria_invalida(self):
        """No se puede usar `ingreso_venta` ni un valor inventado como
        categoria de salida — el ChoiceField solo acepta las 3 validas."""
        from reportes.forms import CajaSalidaForm
        form = CajaSalidaForm(data={
            'tienda': self.tienda.pk,
            'categoria': MovimientoCaja.INGRESO_VENTA,   # invalido para salida
            'monto': '50000',
            'concepto': 'X',
        })
        self.assertFalse(form.is_valid())
        self.assertIn('categoria', form.errors)

    def test_tabla_muestra_columna_categoria(self):
        """El listado de movimientos incluye la columna Categoria con
        badge — para que el admin vea de un vistazo si una salida es
        gasto, compra de inventario o pago de confeccion."""
        self.client.login(username='ana', password='x')
        # Crear movimientos de las 3 categorias para que aparezcan badges.
        registrar_salida(
            tienda=self.tienda, monto=Decimal('100'), concepto='Luz',
            categoria=MovimientoCaja.GASTO_OPERATIVO,
        )
        registrar_salida(
            tienda=self.tienda, monto=Decimal('200'), concepto='Telas',
            categoria=MovimientoCaja.COSTO_INVENTARIO,
        )
        registrar_salida(
            tienda=self.tienda, monto=Decimal('300'), concepto='Confección',
            categoria=MovimientoCaja.COSTO_PRODUCCION,
        )
        resp = self.client.get(reverse('reportes:caja'))
        body = resp.content.decode()
        self.assertIn('<th>Categoría</th>', body)
        self.assertIn('Gasto operativo', body)
        self.assertIn('Compra inventario', body)
        self.assertIn('Confección', body)


class ProduccionViewTests(TestCase):
    """Smoke de /reportes/produccion/ (Fase K)."""

    @classmethod
    def setUpTestData(cls):
        from bodega.models import Bodega, Material, Rendimiento, StockMaterial
        from catalogo.models import Familia, Producto, ProductoVariante

        cls.admin = User.objects.create_superuser('an', 'a@a.cl', 'x')
        cls.tienda = Tienda.objects.create(nombre_organizacion='LV', activa=True)
        cls.bodega = Bodega.objects.create(tienda=cls.tienda, nombre='B-LV')
        material = Material.objects.create(
            nombre='Tela buzo', costo_unitario_referencia=Decimal('40000'),
        )
        fam = Familia.objects.create(nombre='Uniformes')
        prod = Producto.objects.create(
            familia=fam, nombre='Buzo SFJ',
            precio_base=Decimal('30000'), tiene_variantes=True,
        )
        var = ProductoVariante.objects.create(producto=prod, sku='BZ-M')
        Rendimiento.objects.create(material=material, variante=var, unidades_por_rollo=50)
        StockMaterial.objects.create(bodega=cls.bodega, material=material, cantidad=4)

    def test_admin_ve_capacidad(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse('reportes:produccion'))
        self.assertEqual(resp.status_code, 200)
        # py3.9/dj4.2 local usa NBSP como separador de miles → normalizar.
        body = resp.content.decode().replace('\xa0', '.')
        # 4 rollos × 50 u/rollo = 200 unidades
        self.assertIn('200', body)
        # Valor potencial = 200 × $30.000 = $6.000.000 → '6.000.000' con intcomma
        self.assertIn('6.000.000', body)
        # Costo materiales = 4 × $40.000 = $160.000
        self.assertIn('160.000', body)

    def test_no_admin_rebota(self):
        User.objects.create_user('cli', password='x')
        self.client.login(username='cli', password='x')
        resp = self.client.get(reverse('reportes:produccion'))
        self.assertEqual(resp.status_code, 302)
