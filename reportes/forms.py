"""Formularios de la app de reportes.

Por ahora solo tenemos `CajaSalidaForm` — el egreso manual que el admin
registra cuando paga arriendo, sueldos, una compra, etc.
"""

from decimal import Decimal

from django import forms

from bodega.models import Tienda


class CajaSalidaForm(forms.Form):
    tienda = forms.ModelChoiceField(
        queryset=Tienda.objects.filter(activa=True),
        label='Tienda',
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
