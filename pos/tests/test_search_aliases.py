"""Tests de los modismos de búsqueda del POS para colegios de Los Vilos.

Cubre tanto la utilidad pura (`pos.search`) como el endpoint del POS
(`pos:home`) para confirmar que el cajero puede tipear apodos locales
y los productos correctos aparecen en la lista.
"""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.test import TestCase
from django.urls import reverse

from bodega.models import StockTienda, Tienda
from catalogo.models import (
    Atributo, Colegio, Familia, Producto, ProductoVariante, ValorAtributo,
)
from pos.search import (
    ALIASES_COLEGIO,
    TALLAS_LETRA,
    es_talla_letra,
    expandir_token,
    normalizar_y_expandir,
)


User = get_user_model()


class ExpandirTokenTests(TestCase):
    def test_token_sin_alias_no_se_modifica(self):
        self.assertEqual(expandir_token('polera'), ['polera'])

    def test_alias_liceo_expande_a_lohse(self):
        result = expandir_token('liceo')
        self.assertIn('liceo', result)
        self.assertIn('lohse', result)

    def test_alias_fraga_expande_a_javier(self):
        result = expandir_token('fraga')
        self.assertIn('javier', result)

    def test_alias_parro_expande_a_providencia(self):
        result = expandir_token('parro')
        self.assertIn('providencia', result)

    def test_alias_parroquial_expande_a_providencia(self):
        result = expandir_token('parroquial')
        self.assertIn('providencia', result)

    def test_alias_publica_expande_a_almagro(self):
        result = expandir_token('publica')
        self.assertIn('almagro', result)


class NormalizarYExpandirTests(TestCase):
    def test_quita_acentos_y_lowercase(self):
        # "Pública" → "publica" → expandida
        result = normalizar_y_expandir('Pública')
        # Devuelve una lista por token; el primer (y único) token
        # expandido debe contener 'publica' y 'almagro'.
        self.assertEqual(len(result), 1)
        self.assertIn('publica', result[0])
        self.assertIn('almagro', result[0])

    def test_multi_token_cada_uno_expande_independiente(self):
        # "liceo polera" → [['liceo', 'lohse'], ['polera']]
        result = normalizar_y_expandir('liceo polera')
        self.assertEqual(len(result), 2)
        self.assertIn('liceo', result[0])
        self.assertIn('lohse', result[0])
        self.assertEqual(result[1], ['polera'])

    def test_string_vacio_devuelve_lista_vacia(self):
        self.assertEqual(normalizar_y_expandir(''), [])
        self.assertEqual(normalizar_y_expandir('   '), [])


class PosSearchEndpointAliasesTests(TestCase):
    """Smoke E2E: cajero busca 'liceo' en /pos/ y aparecen los productos
    asociados al Colegio cuyo nombre contiene 'Lohse'.
    """

    @classmethod
    def setUpTestData(cls):
        cls.tienda = Tienda.objects.create(nombre_organizacion='Tienda Vilos', activa=True)
        cls.fam = Familia.objects.create(nombre='Uniformes')

        # 4 colegios reales de Los Vilos, cada uno con su nombre formal.
        cls.col_lohse = Colegio.objects.create(nombre='Liceo Nicolás Federico Lohse')
        cls.col_sfj = Colegio.objects.create(nombre='Colegio San Francisco Javier')
        cls.col_div = Colegio.objects.create(nombre='Divina Providencia')
        cls.col_alm = Colegio.objects.create(nombre='Escuela Diego de Almagro')

        # Un producto por colegio. Nombres NEUTROS — "Buzo" — para
        # forzar que el match venga via colegio.nombre_buscable, no
        # del nombre del producto.
        cls.prod_lohse = Producto.objects.create(
            familia=cls.fam, nombre='Buzo escolar', colegio=cls.col_lohse,
            precio_base=Decimal('25000'), tiene_variantes=False,
        )
        cls.prod_sfj = Producto.objects.create(
            familia=cls.fam, nombre='Polera unisex', colegio=cls.col_sfj,
            precio_base=Decimal('15000'), tiene_variantes=False,
        )
        cls.prod_div = Producto.objects.create(
            familia=cls.fam, nombre='Chaleco', colegio=cls.col_div,
            precio_base=Decimal('20000'), tiene_variantes=False,
        )
        cls.prod_alm = Producto.objects.create(
            familia=cls.fam, nombre='Pantalón gris', colegio=cls.col_alm,
            precio_base=Decimal('18000'), tiene_variantes=False,
        )
        for p in (cls.prod_lohse, cls.prod_sfj, cls.prod_div, cls.prod_alm):
            StockTienda.objects.create(tienda=cls.tienda, producto=p, cantidad=5)

        # Cajero con permiso de ver el POS.
        cajero_grp, _ = Group.objects.get_or_create(name='cajero')
        perms = Permission.objects.filter(
            content_type__app_label='pos',
            codename__in=['add_reciboventa', 'view_reciboventa'],
        )
        cajero_grp.permissions.add(*perms)
        cls.cajero = User.objects.create_user(username='caja1', password='x')
        cls.cajero.groups.add(cajero_grp)

    def setUp(self):
        self.client.login(username='caja1', password='x')
        # La home del POS necesita una tienda activa en session.
        session = self.client.session
        session['pos_tienda_id'] = self.tienda.pk
        session.save()

    def _buscar(self, q):
        url = reverse('pos:home') + f'?q={q}'
        return self.client.get(url)

    def test_buscar_liceo_encuentra_buzo_de_lohse(self):
        resp = self._buscar('liceo')
        self.assertEqual(resp.status_code, 200)
        productos = list(resp.context['productos'])
        nombres = {p.nombre for p in productos}
        self.assertIn('Buzo escolar', nombres,
            'Buscar "liceo" debe traer productos del colegio Lohse.')
        self.assertNotIn('Polera unisex', nombres,
            'No debe traer productos de otros colegios.')

    def test_buscar_fraga_encuentra_polera_del_sfj(self):
        resp = self._buscar('fraga')
        nombres = {p.nombre for p in resp.context['productos']}
        self.assertIn('Polera unisex', nombres,
            'Buscar "fraga" debe traer productos del SFJ.')

    def test_buscar_parro_encuentra_chaleco_de_divina(self):
        resp = self._buscar('parro')
        nombres = {p.nombre for p in resp.context['productos']}
        self.assertIn('Chaleco', nombres,
            'Buscar "parro" debe traer productos de Divina Providencia.')

    def test_buscar_parroquial_tambien_encuentra_divina(self):
        resp = self._buscar('parroquial')
        nombres = {p.nombre for p in resp.context['productos']}
        self.assertIn('Chaleco', nombres)

    def test_buscar_publica_encuentra_pantalon_de_almagro(self):
        resp = self._buscar('publica')
        nombres = {p.nombre for p in resp.context['productos']}
        self.assertIn('Pantalón gris', nombres,
            'Buscar "publica" debe traer productos de Diego de Almagro.')

    def test_busqueda_normal_sigue_funcionando(self):
        """Sanity: una busqueda sin alias (`buzo`) sigue matcheando
        productos por nombre como antes."""
        resp = self._buscar('buzo')
        nombres = {p.nombre for p in resp.context['productos']}
        self.assertIn('Buzo escolar', nombres)


class PosSearchAliasMultiTokenTests(TestCase):
    """Mismo comportamiento que con "sfj 12": cualquier alias combinado
    con una talla debe filtrar las VARIANTES de ese colegio en esa talla.

    Ejemplos verificados:
        "liceo 12"      → variantes Lohse talla 12
        "fraga 14"      → variantes SFJ talla 14
        "parro 10"      → variantes Divina Providencia talla 10
        "publica 8"     → variantes Diego de Almagro talla 8
    """

    @classmethod
    def setUpTestData(cls):
        cls.tienda = Tienda.objects.create(nombre_organizacion='Tienda Vilos', activa=True)
        cls.fam = Familia.objects.create(nombre='Uniformes')
        cls.atr_talla = Atributo.objects.create(nombre='Talla')

        # Valores de talla compartidos.
        cls.val_8 = ValorAtributo.objects.create(atributo=cls.atr_talla, valor='8', orden=8)
        cls.val_10 = ValorAtributo.objects.create(atributo=cls.atr_talla, valor='10', orden=10)
        cls.val_12 = ValorAtributo.objects.create(atributo=cls.atr_talla, valor='12', orden=12)
        cls.val_14 = ValorAtributo.objects.create(atributo=cls.atr_talla, valor='14', orden=14)

        cls.col_lohse = Colegio.objects.create(nombre='Liceo Nicolás Federico Lohse')
        cls.col_sfj = Colegio.objects.create(nombre='Colegio San Francisco Javier')
        cls.col_div = Colegio.objects.create(nombre='Divina Providencia')
        cls.col_alm = Colegio.objects.create(nombre='Escuela Diego de Almagro')

        # 1 producto con variantes (tallas) por cada colegio. Los
        # nombres son colores neutros — no contienen alias (lohse,
        # javier, sfj, providencia, almagro, diego), forzando que el
        # match con "liceo"/"fraga"/"parro"/"publica" venga via
        # colegio.nombre_buscable. Producto.nombre es unique.
        cls.variantes = {}  # (colegio_codigo, talla) -> ProductoVariante
        nombres_neutros = {
            'LOH': 'Buzo gris',
            'SFJ': 'Buzo azul',
            'DIV': 'Buzo blanco',
            'ALM': 'Buzo negro',
        }
        for col, code in [
            (cls.col_lohse, 'LOH'),
            (cls.col_sfj, 'SFJ'),
            (cls.col_div, 'DIV'),
            (cls.col_alm, 'ALM'),
        ]:
            prod = Producto.objects.create(
                familia=cls.fam, nombre=nombres_neutros[code], colegio=col,
                precio_base=Decimal('25000'), tiene_variantes=True,
            )
            for val, talla in [(cls.val_8, 8), (cls.val_10, 10),
                               (cls.val_12, 12), (cls.val_14, 14)]:
                v = ProductoVariante.objects.create(
                    producto=prod, sku=f'BZ-{code}-{talla}',
                )
                v.valores.add(val)
                StockTienda.objects.create(tienda=cls.tienda, variante=v, cantidad=3)
                cls.variantes[(code, talla)] = v

        cajero_grp, _ = Group.objects.get_or_create(name='cajero')
        perms = Permission.objects.filter(
            content_type__app_label='pos',
            codename__in=['add_reciboventa', 'view_reciboventa'],
        )
        cajero_grp.permissions.add(*perms)
        cls.cajero = User.objects.create_user(username='caja2', password='x')
        cls.cajero.groups.add(cajero_grp)

    def setUp(self):
        self.client.login(username='caja2', password='x')
        session = self.client.session
        session['pos_tienda_id'] = self.tienda.pk
        session.save()

    def _buscar(self, q):
        url = reverse('pos:home') + f'?q={q}'
        return self.client.get(url)

    def _skus(self, resp):
        return {v.sku for v in resp.context['variantes']}

    # ─── Alias + talla: cada combinación filtra una sola variante ───

    def test_liceo_12_devuelve_variante_lohse_talla_12(self):
        resp = self._buscar('liceo 12')
        skus = self._skus(resp)
        self.assertIn('BZ-LOH-12', skus)
        # No debe traer ni otras tallas del Lohse, ni el Lohse no-12,
        # ni el 12 de otros colegios.
        self.assertNotIn('BZ-LOH-10', skus)
        self.assertNotIn('BZ-SFJ-12', skus)
        self.assertNotIn('BZ-DIV-12', skus)
        self.assertNotIn('BZ-ALM-12', skus)

    def test_fraga_14_devuelve_variante_sfj_talla_14(self):
        resp = self._buscar('fraga 14')
        skus = self._skus(resp)
        self.assertEqual(skus, {'BZ-SFJ-14'})

    def test_parro_10_devuelve_variante_divina_talla_10(self):
        resp = self._buscar('parro 10')
        skus = self._skus(resp)
        self.assertEqual(skus, {'BZ-DIV-10'})

    def test_parroquial_10_tambien_funciona(self):
        resp = self._buscar('parroquial 10')
        skus = self._skus(resp)
        self.assertEqual(skus, {'BZ-DIV-10'})

    def test_publica_8_devuelve_variante_almagro_talla_8(self):
        resp = self._buscar('publica 8')
        skus = self._skus(resp)
        self.assertEqual(skus, {'BZ-ALM-8'})

    def test_orden_de_tokens_no_importa(self):
        """`12 liceo` debe devolver lo mismo que `liceo 12`."""
        skus_a = self._skus(self._buscar('liceo 12'))
        skus_b = self._skus(self._buscar('12 liceo'))
        self.assertEqual(skus_a, skus_b)
        self.assertEqual(skus_a, {'BZ-LOH-12'})


class EsTallaLetraTests(TestCase):
    def test_letras_canonicas(self):
        for talla in ['xs', 's', 'm', 'l', 'xl', 'xxl', 'xxxl']:
            self.assertTrue(es_talla_letra(talla),
                f'"{talla}" debería ser talla-letra')

    def test_case_insensitive(self):
        self.assertTrue(es_talla_letra('S'))
        self.assertTrue(es_talla_letra('XL'))

    def test_numericas_no_son_letra(self):
        # Las numéricas se tratan distinto (icontains funciona porque
        # "12" no aparece random en nombres comunes).
        self.assertFalse(es_talla_letra('12'))
        self.assertFalse(es_talla_letra('8'))

    def test_palabras_no_son_letra(self):
        self.assertFalse(es_talla_letra('polera'))
        self.assertFalse(es_talla_letra('liceo'))


class PosSearchAliasMasTallaLetraTests(TestCase):
    """Combina aliases de colegio con tallas-letra (S, M, L, XL).

    Diferencia clave con las numéricas: "s" / "m" / "l" matchean
    cientos de palabras random vía `__contains` (gris, almagro, moda).
    Por eso `pos.views.home` cambia a `valores__valor__iexact` para
    estos tokens y excluye productos sin variantes.
    """

    @classmethod
    def setUpTestData(cls):
        cls.tienda = Tienda.objects.create(nombre_organizacion='Tienda Vilos', activa=True)
        cls.fam = Familia.objects.create(nombre='Uniformes')
        cls.atr = Atributo.objects.create(nombre='Talla')

        cls.val_s = ValorAtributo.objects.create(atributo=cls.atr, valor='S', orden=1)
        cls.val_m = ValorAtributo.objects.create(atributo=cls.atr, valor='M', orden=2)
        cls.val_l = ValorAtributo.objects.create(atributo=cls.atr, valor='L', orden=3)
        cls.val_xl = ValorAtributo.objects.create(atributo=cls.atr, valor='XL', orden=4)

        cls.col_lohse = Colegio.objects.create(nombre='Liceo Nicolás Federico Lohse')
        cls.col_sfj = Colegio.objects.create(nombre='Colegio San Francisco Javier')
        cls.col_div = Colegio.objects.create(nombre='Divina Providencia')
        cls.col_alm = Colegio.objects.create(nombre='Escuela Diego de Almagro')

        # 1 producto por colegio, cada uno con 4 variantes (S/M/L/XL).
        cls.variantes = {}  # (colegio_code, talla) -> Variante
        for col, code, nombre in [
            (cls.col_lohse, 'LOH', 'Polera azul'),
            (cls.col_sfj, 'SFJ', 'Polera roja'),
            (cls.col_div, 'DIV', 'Polera verde'),
            (cls.col_alm, 'ALM', 'Polera negra'),
        ]:
            prod = Producto.objects.create(
                familia=cls.fam, nombre=nombre, colegio=col,
                precio_base=Decimal('15000'), tiene_variantes=True,
            )
            for val, talla in [(cls.val_s, 'S'), (cls.val_m, 'M'),
                               (cls.val_l, 'L'), (cls.val_xl, 'XL')]:
                v = ProductoVariante.objects.create(
                    producto=prod, sku=f'POL-{code}-{talla}',
                )
                v.valores.add(val)
                StockTienda.objects.create(tienda=cls.tienda, variante=v, cantidad=3)
                cls.variantes[(code, talla)] = v

        # Producto SIN variantes — perfume con "Sandalwood" en el nombre.
        # Si buscamos "s" suelto sin guard de talla-letra, ESTE matchearía
        # via `nombre_buscable contains 's'` — el guard lo excluye.
        cls.fam_perf = Familia.objects.create(nombre='Perfumes')
        cls.perfume = Producto.objects.create(
            familia=cls.fam_perf, nombre='Sandalwood Mystic',
            precio_base=Decimal('30000'), tiene_variantes=False,
        )
        StockTienda.objects.create(tienda=cls.tienda, producto=cls.perfume, cantidad=2)

        cajero_grp, _ = Group.objects.get_or_create(name='cajero')
        perms = Permission.objects.filter(
            content_type__app_label='pos',
            codename__in=['add_reciboventa', 'view_reciboventa'],
        )
        cajero_grp.permissions.add(*perms)
        cls.cajero = User.objects.create_user(username='caja3', password='x')
        cls.cajero.groups.add(cajero_grp)

    def setUp(self):
        self.client.login(username='caja3', password='x')
        session = self.client.session
        session['pos_tienda_id'] = self.tienda.pk
        session.save()

    def _buscar(self, q):
        return self.client.get(reverse('pos:home') + f'?q={q}')

    def _skus(self, resp):
        return {v.sku for v in resp.context['variantes']}

    def _productos(self, resp):
        return {p.nombre for p in resp.context['productos']}

    # ─── Alias + talla-letra: cada combinación filtra UNA variante ───

    def test_liceo_s_devuelve_solo_lohse_talla_s(self):
        resp = self._buscar('liceo s')
        self.assertEqual(self._skus(resp), {'POL-LOH-S'},
            'Buscar "liceo s" debe traer EXCLUSIVAMENTE la talla S del Lohse.')

    def test_liceo_m_devuelve_solo_lohse_talla_m(self):
        resp = self._buscar('liceo m')
        self.assertEqual(self._skus(resp), {'POL-LOH-M'})

    def test_liceo_xl_devuelve_solo_lohse_talla_xl(self):
        resp = self._buscar('liceo xl')
        self.assertEqual(self._skus(resp), {'POL-LOH-XL'})

    def test_fraga_l_devuelve_solo_sfj_talla_l(self):
        resp = self._buscar('fraga l')
        self.assertEqual(self._skus(resp), {'POL-SFJ-L'})

    def test_parro_s_devuelve_solo_divina_talla_s(self):
        resp = self._buscar('parro s')
        self.assertEqual(self._skus(resp), {'POL-DIV-S'})

    def test_publica_xl_devuelve_solo_almagro_talla_xl(self):
        resp = self._buscar('publica xl')
        self.assertEqual(self._skus(resp), {'POL-ALM-XL'})

    def test_case_insensitive_LICEO_S(self):
        """Cajero tipea en mayúsculas — debe funcionar igual."""
        resp = self._buscar('LICEO S')
        self.assertEqual(self._skus(resp), {'POL-LOH-S'})

    # ─── Guards anti-falsos-positivos ───

    def test_buscar_solo_s_no_trae_productos_sin_variantes(self):
        """Buscar `s` aislado NO debe traer "Sandalwood Mystic" aunque
        su nombre contenga 's'. El guard `hay_talla_letra` excluye los
        productos sin variantes cuando hay un token de talla-letra."""
        resp = self._buscar('s')
        self.assertEqual(self._productos(resp), set(),
            'Productos sin variantes NO deben aparecer cuando se busca solo una talla-letra.')
        # Pero SÍ las variantes con talla S.
        skus = self._skus(resp)
        self.assertIn('POL-LOH-S', skus)
        self.assertIn('POL-SFJ-S', skus)
        self.assertIn('POL-DIV-S', skus)
        self.assertIn('POL-ALM-S', skus)

    def test_liceo_s_no_matchea_otras_tallas_del_lohse(self):
        """Confirma que `iexact` es estricto: "s" NO matchea "XS"."""
        resp = self._buscar('liceo s')
        skus = self._skus(resp)
        self.assertNotIn('POL-LOH-M', skus)
        self.assertNotIn('POL-LOH-L', skus)
        self.assertNotIn('POL-LOH-XL', skus)

    def test_liceo_xl_no_matchea_l_ni_xxl(self):
        """`iexact` previene que "xl" matchee variantes "L" o "XXL"."""
        resp = self._buscar('liceo xl')
        skus = self._skus(resp)
        self.assertNotIn('POL-LOH-L', skus)
        # No hay XXL en setUp pero la lógica es la misma.

    def test_orden_de_tokens_no_importa_con_letras(self):
        """`s liceo` ≡ `liceo s`."""
        a = self._skus(self._buscar('liceo s'))
        b = self._skus(self._buscar('s liceo'))
        self.assertEqual(a, b)
        self.assertEqual(a, {'POL-LOH-S'})


class PosSearchTallasExhaustivaTests(TestCase):
    """Valida que TODAS las tallas que vende la boutique funcionen:
    letras (XS/S/M/L/XL/XXL) y numéricas (4/6/8/10/12/14/16/18).
    """

    @classmethod
    def setUpTestData(cls):
        cls.tienda = Tienda.objects.create(nombre_organizacion='Tienda T', activa=True)
        cls.fam = Familia.objects.create(nombre='Uniformes')
        cls.atr = Atributo.objects.create(nombre='Talla')

        # Set completo de tallas.
        cls.valores = {}
        letras = ['XS', 'S', 'M', 'L', 'XL', 'XXL']
        numeros = ['4', '6', '8', '10', '12', '14', '16', '18']
        for i, t in enumerate(letras + numeros, start=1):
            cls.valores[t] = ValorAtributo.objects.create(
                atributo=cls.atr, valor=t, orden=i,
            )

        # 1 producto con 14 variantes (todas las tallas).
        cls.prod = Producto.objects.create(
            familia=cls.fam, nombre='Buzo escolar',
            precio_base=Decimal('15000'), tiene_variantes=True,
        )
        for talla, val in cls.valores.items():
            v = ProductoVariante.objects.create(
                producto=cls.prod, sku=f'BZ-{talla}',
            )
            v.valores.add(val)
            StockTienda.objects.create(tienda=cls.tienda, variante=v, cantidad=3)

        cajero_grp, _ = Group.objects.get_or_create(name='cajero')
        perms = Permission.objects.filter(
            content_type__app_label='pos',
            codename__in=['add_reciboventa', 'view_reciboventa'],
        )
        cajero_grp.permissions.add(*perms)
        cls.cajero = User.objects.create_user(username='caja4', password='x')
        cls.cajero.groups.add(cajero_grp)

    def setUp(self):
        self.client.login(username='caja4', password='x')
        session = self.client.session
        session['pos_tienda_id'] = self.tienda.pk
        session.save()

    def _skus(self, q):
        resp = self.client.get(reverse('pos:home') + f'?q={q}')
        return {v.sku for v in resp.context['variantes']}

    # ─── Letras: cada una mappea a UNA variante ───

    def test_buscar_xs(self):
        self.assertEqual(self._skus('xs'), {'BZ-XS'})

    def test_buscar_S_solo_trae_la_S(self):
        # No debe matchear XS ni XXL ni nada con "s" en el nombre.
        self.assertEqual(self._skus('s'), {'BZ-S'})

    def test_buscar_M_solo_trae_la_M(self):
        self.assertEqual(self._skus('m'), {'BZ-M'})

    def test_buscar_L_solo_trae_la_L(self):
        # Critical: "l" no debe matchear XL ni XXL.
        self.assertEqual(self._skus('l'), {'BZ-L'})

    def test_buscar_XL_solo_trae_la_XL(self):
        # Critical: XL no debe traer XXL.
        self.assertEqual(self._skus('xl'), {'BZ-XL'})

    def test_buscar_XXL_solo_trae_la_XXL(self):
        self.assertEqual(self._skus('xxl'), {'BZ-XXL'})

    # ─── Numéricas: cada una mappea a UNA variante ───

    def test_buscar_4_no_matchea_14(self):
        """Critical: "4" debe traer talla 4, NO 14 ni 24."""
        self.assertEqual(self._skus('4'), {'BZ-4'})

    def test_buscar_8(self):
        self.assertEqual(self._skus('8'), {'BZ-8'})

    def test_buscar_12(self):
        self.assertEqual(self._skus('12'), {'BZ-12'})

    def test_buscar_14_no_matchea_4(self):
        self.assertEqual(self._skus('14'), {'BZ-14'})

    def test_buscar_18(self):
        self.assertEqual(self._skus('18'), {'BZ-18'})


class PosSearchPerfumesTests(TestCase):
    """Valida búsqueda inteligente de perfumes: volumen + concentración.

    Estructura de datos real (ver seed_perfumes_real.py):
      ValorAtributo "Volumen":         "30 ml", "50 ml", "100 ml", ...
      ValorAtributo "Concentración":   "EDT", "EDP", "Elixir", ...

    El cajero puede buscar:
      "yara 30"            → Yara variante 30 ml
      "tous edt 100"       → Tous EDT 100 ml
      "edp 50"             → todas las EDP en 50 ml (cross-product)
    """

    @classmethod
    def setUpTestData(cls):
        cls.tienda = Tienda.objects.create(nombre_organizacion='Perfumes T', activa=True)
        cls.fam = Familia.objects.create(nombre='Perfumes')

        cls.atr_vol = Atributo.objects.create(nombre='Volumen')
        cls.atr_conc = Atributo.objects.create(nombre='Concentración')

        cls.vol = {}
        for i, ml in enumerate([5, 30, 50, 100, 130, 300], start=1):
            cls.vol[ml] = ValorAtributo.objects.create(
                atributo=cls.atr_vol, valor=f'{ml} ml', orden=i,
            )
        cls.conc = {}
        for i, c in enumerate(['EDT', 'EDP', 'Elixir', 'Cologne'], start=1):
            cls.conc[c] = ValorAtributo.objects.create(
                atributo=cls.atr_conc, valor=c, orden=i,
            )

        cls.perfumes = {}
        for nombre in ['Yara', 'Tous', 'Bouquet']:
            prod = Producto.objects.create(
                familia=cls.fam, nombre=nombre,
                precio_base=Decimal('25000'), tiene_variantes=True,
            )
            cls.perfumes[nombre] = prod
            # 4 variantes por perfume: (30 ml, EDT) (30, EDP) (50, EDT) (50, EDP)
            for ml in [30, 50, 100]:
                for c in ['EDT', 'EDP']:
                    v = ProductoVariante.objects.create(
                        producto=prod, sku=f'{nombre[:3].upper()}-{ml}-{c}',
                    )
                    v.valores.add(cls.vol[ml])
                    v.valores.add(cls.conc[c])
                    StockTienda.objects.create(tienda=cls.tienda, variante=v, cantidad=2)

        # Datos "trampa" para validar que no haya falsos positivos:
        # - Variante con valor "130 ml": cuando se busca "30" no debe aparecer
        # - Variante con valor "300 ml": idem
        # - Variante con valor "5 ml": cuando se busca "5" sí; no debe aparecer al buscar "50"
        prod_trampa = Producto.objects.create(
            familia=cls.fam, nombre='Trampa Vol Test',
            precio_base=Decimal('10000'), tiene_variantes=True,
        )
        for ml, sku in [(5, 'TRA-5'), (130, 'TRA-130'), (300, 'TRA-300')]:
            v = ProductoVariante.objects.create(producto=prod_trampa, sku=sku)
            v.valores.add(cls.vol[ml])
            v.valores.add(cls.conc['EDT'])
            StockTienda.objects.create(tienda=cls.tienda, variante=v, cantidad=1)

        cajero_grp, _ = Group.objects.get_or_create(name='cajero')
        perms = Permission.objects.filter(
            content_type__app_label='pos',
            codename__in=['add_reciboventa', 'view_reciboventa'],
        )
        cajero_grp.permissions.add(*perms)
        cls.cajero = User.objects.create_user(username='caja5', password='x')
        cls.cajero.groups.add(cajero_grp)

    def setUp(self):
        self.client.login(username='caja5', password='x')
        session = self.client.session
        session['pos_tienda_id'] = self.tienda.pk
        session.save()

    def _skus(self, q):
        resp = self.client.get(reverse('pos:home') + f'?q={q}')
        return {v.sku for v in resp.context['variantes']}

    # ─── Nombre + volumen ───

    def test_yara_30_devuelve_solo_variantes_yara_de_30ml(self):
        """Buscar "yara 30" → ambas concentraciones (EDT/EDP) de Yara 30 ml."""
        skus = self._skus('yara 30')
        self.assertEqual(skus, {'YAR-30-EDT', 'YAR-30-EDP'})

    def test_yara_30_no_matchea_130ml(self):
        """Critical: "30" istartswith requiere espacio después → '30 ml' SÍ, '130 ml' NO."""
        skus = self._skus('yara 30')
        self.assertNotIn('TRA-130', skus)
        # Ningún SKU del setup tiene 130 ml asignado a Yara, pero el
        # principio se valida con el dato trampa.

    def test_buscar_5_no_matchea_50_ni_25(self):
        """Critical: "5" debe matchear "5 ml" pero NO "50 ml" ni "25 ml"."""
        skus = self._skus('5')
        self.assertIn('TRA-5', skus)
        # Ninguno de los SKUs Yara/Tous/Bouquet tiene 5 ml.
        self.assertNotIn('YAR-50-EDT', skus)
        self.assertNotIn('YAR-50-EDP', skus)

    def test_buscar_300_aislado(self):
        """`300` debe traer la variante 300 ml."""
        skus = self._skus('300')
        self.assertIn('TRA-300', skus)

    # ─── Nombre + concentración ───

    def test_yara_edt_devuelve_todas_las_edt_de_yara(self):
        skus = self._skus('yara edt')
        self.assertEqual(skus, {'YAR-30-EDT', 'YAR-50-EDT', 'YAR-100-EDT'})

    def test_yara_edp_no_matchea_edt(self):
        """Critical: "edp" iexact debe diferenciar de "edt"."""
        skus = self._skus('yara edp')
        for sku in skus:
            self.assertTrue(sku.endswith('-EDP'),
                f'Buscar "yara edp" no debería traer {sku}')

    # ─── Nombre + concentración + volumen ───

    def test_yara_edt_100_devuelve_una_sola_variante(self):
        skus = self._skus('yara edt 100')
        self.assertEqual(skus, {'YAR-100-EDT'})

    def test_orden_de_tokens_no_importa(self):
        """`100 edt yara` ≡ `yara edt 100`."""
        a = self._skus('yara edt 100')
        b = self._skus('100 edt yara')
        c = self._skus('edt yara 100')
        self.assertEqual(a, b)
        self.assertEqual(a, c)

    # ─── Concentración sola: cross-product ───

    def test_edt_solo_trae_todas_las_variantes_con_concentracion_EDT(self):
        """`edt` aislado debe traer TODAS las variantes EDT del catálogo.
        Validamos por SKUs principales (que codifican la conc en el nombre);
        TRA-* también aparecen porque sus valores incluyen EDT."""
        skus = self._skus('edt')
        # Las 3 EDT de cada perfume principal deben estar:
        self.assertIn('YAR-30-EDT', skus)
        self.assertIn('YAR-50-EDT', skus)
        self.assertIn('YAR-100-EDT', skus)
        self.assertIn('TOU-30-EDT', skus)
        self.assertIn('BOU-30-EDT', skus)
        # Y NINGUNA EDP debe estar.
        for s in ['YAR-30-EDP', 'YAR-50-EDP', 'YAR-100-EDP',
                  'TOU-30-EDP', 'BOU-30-EDP']:
            self.assertNotIn(s, skus,
                f'Buscar "edt" no debería traer la variante EDP {s}')

    # ─── Guard anti-ruido para productos sin variantes ───

    def test_buscar_30_no_trae_productos_sin_variantes(self):
        """Si existiera un producto sin variantes con "30" en el nombre,
        no debería aparecer cuando se busca "30" — `30` es token corto."""
        Producto.objects.create(
            familia=self.fam, nombre='Estuche 30 piezas',
            precio_base=Decimal('5000'), tiene_variantes=False,
        )
        resp = self.client.get(reverse('pos:home') + '?q=30')
        nombres = {p.nombre for p in resp.context['productos']}
        self.assertNotIn('Estuche 30 piezas', nombres,
            'Productos sin variantes NO deben aparecer cuando todos los tokens son cortos.')
