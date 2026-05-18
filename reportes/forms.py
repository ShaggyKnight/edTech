"""Formularios de la app de reportes.

Por ahora solo tenemos `CajaSalidaForm` — el egreso manual que el admin
registra cuando paga arriendo, sueldos, una compra, etc.
"""

from decimal import Decimal

from django import forms

from bodega.models import Tienda
from contabilidad.models import MovimientoCaja


# Categorias que tienen sentido para una SALIDA manual desde la UI.
# Excluimos INGRESO_VENTA (no es salida) y "OTRO" (default vago) para
# obligar al admin a elegir conscientemente cómo contabilizar el egreso.
CATEGORIAS_SALIDA = [
    (MovimientoCaja.GASTO_OPERATIVO,
     'Gasto operativo — arriendo, sueldos, luz, agua, WiFi, mantención'),
    (MovimientoCaja.COSTO_INVENTARIO,
     'Compra de inventario — telas, perfumes, productos para revender'),
    (MovimientoCaja.COSTO_PRODUCCION,
     'Pago a confección — quien cose las prendas'),
]


class CajaSalidaForm(forms.Form):
    tienda = forms.ModelChoiceField(
        queryset=Tienda.objects.filter(activa=True),
        label='Tienda',
    )
    # Categoria explicita: corrige un bug contable que existia cuando
    # todas las salidas se cargaban como `GASTO_OPERATIVO` por default.
    # Las compras de inventario y los pagos a confección son ACTIVOS
    # contables, NO gastos del período — engordan el inventario y solo
    # se traducen a "costo de venta" cuando esa mercaderia se vende.
    # Si se cuentan como gasto operativo, el EERR pierde precision y
    # el margen bruto queda subvalorado.
    categoria = forms.ChoiceField(
        choices=CATEGORIAS_SALIDA,
        initial=MovimientoCaja.GASTO_OPERATIVO,
        label='Tipo de salida',
        help_text=(
            'Importante para la contabilidad. Las compras de tela / perfumes '
            'y el pago a quien confecciona NO son "gastos del mes" — se '
            'cargan como inventario y se gastan cuando se vende el producto.'
        ),
    )
    monto = forms.DecimalField(
        max_digits=12, decimal_places=2, min_value=Decimal('0.01'),
        label='Monto',
    )
    concepto = forms.CharField(
        max_length=200,
        label='Concepto',
        help_text='Ej: Arriendo local abril, pago proveedor Perfumes SA',
    )
