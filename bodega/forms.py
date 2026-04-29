"""Formularios de gestión de catálogo desde la pantalla de bodega.

Estos forms son la versión "operativa" del Django admin: pensados para
que el bodeguero/admin del negocio (no el superusuario que toca SQL)
pueda crear y editar productos, variantes y materiales sin entrar a
/admin/.
"""
from __future__ import annotations

from django import forms
from django.core.exceptions import ValidationError

from catalogo.models import (
    Atributo,
    Colegio,
    Familia,
    Producto,
    ProductoVariante,
    ValorAtributo,
)


# Atributos que tienen sentido en un selector de variante. Si más adelante
# agregás "Color" o "Tipo", los listás acá. El form solo muestra los que
# tienen valores cargados.
ATRIBUTOS_VARIANTES = ('Talla', 'Volumen', 'Concentración')


class ProductoForm(forms.ModelForm):
    """Crea o edita un Producto. No maneja variantes — eso va en otro form."""

    class Meta:
        model = Producto
        fields = [
            'nombre', 'familia', 'colegio',
            'descripcion',
            'precio_base', 'precio_costo',
            'tiene_variantes', 'activo',
            'imagen',
        ]
        widgets = {
            'nombre': forms.TextInput(attrs={'class': 'bo-input'}),
            'familia': forms.Select(attrs={'class': 'bo-select'}),
            'colegio': forms.Select(attrs={'class': 'bo-select'}),
            'descripcion': forms.Textarea(attrs={'class': 'bo-textarea', 'rows': 3}),
            'precio_base': forms.NumberInput(attrs={'class': 'bo-input', 'min': 0}),
            'precio_costo': forms.NumberInput(attrs={'class': 'bo-input', 'min': 0}),
            'tiene_variantes': forms.CheckboxInput(),
            'activo': forms.CheckboxInput(),
            'imagen': forms.ClearableFileInput(),
        }
        help_texts = {
            'colegio': 'Solo si es uniforme escolar (lleva insignia bordada).',
            'tiene_variantes': 'Marcá si el producto se vende por talla, volumen, etc. '
                               'En el siguiente paso definís las variantes.',
            'precio_costo': 'Costo unitario. Sirve para calcular margen y valorizar inventario.',
        }


class ProductoVarianteForm(forms.ModelForm):
    """Crea o edita una variante de un producto.

    Los atributos (talla / volumen / concentración) se muestran como
    selects opcionales: el bodeguero pone los que apliquen al producto.
    Para una camisa de uniforme: solo Talla. Para un perfume: Volumen +
    Concentración.
    """
    # Campos dinámicos para cada atributo conocido. Se llenan en __init__
    # leyendo los `Atributo` de la DB que tienen al menos 1 valor.
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        instance = kwargs.get('instance')

        for nombre in ATRIBUTOS_VARIANTES:
            try:
                attr = Atributo.objects.get(nombre=nombre)
            except Atributo.DoesNotExist:
                continue
            valores_qs = attr.valores.all().order_by('orden', 'valor')
            if not valores_qs.exists():
                continue
            initial = None
            if instance is not None:
                seleccionado = instance.valores.filter(atributo=attr).first()
                if seleccionado:
                    initial = seleccionado.pk
            self.fields[f'attr_{attr.pk}'] = forms.ModelChoiceField(
                queryset=valores_qs,
                required=False,
                label=nombre,
                widget=forms.Select(attrs={'class': 'bo-select'}),
                initial=initial,
            )

    class Meta:
        model = ProductoVariante
        fields = ['sku', 'precio_override', 'activa']
        widgets = {
            'sku': forms.TextInput(attrs={'class': 'bo-input'}),
            'precio_override': forms.NumberInput(attrs={'class': 'bo-input', 'min': 0}),
            'activa': forms.CheckboxInput(),
        }
        help_texts = {
            'sku': 'Código único. Ej: BUZO-SFJ-M, YARA-30ML-EDP.',
            'precio_override': 'Si esta variante tiene precio distinto al producto base. '
                               'Vacío = usa el precio del producto.',
        }

    def save(self, commit=True, producto=None):
        v = super().save(commit=False)
        if producto:
            v.producto = producto
        if commit:
            v.save()
            # Limpio valores anteriores y agrego los seleccionados.
            v.valores.clear()
            for nombre in ATRIBUTOS_VARIANTES:
                try:
                    attr = Atributo.objects.get(nombre=nombre)
                except Atributo.DoesNotExist:
                    continue
                key = f'attr_{attr.pk}'
                val = self.cleaned_data.get(key)
                if val:
                    v.valores.add(val)
        return v


class StockInicialForm(forms.Form):
    """Form chico para cargar stock inicial al crear una variante o
    producto sin variantes. Pensado para bodeguero/admin."""
    tienda = forms.IntegerField(min_value=1, required=False, widget=forms.HiddenInput)
    cantidad = forms.IntegerField(
        min_value=0, initial=0, required=False,
        widget=forms.NumberInput(attrs={'class': 'bo-input', 'min': 0}),
        help_text='Unidades en stock inicial. Cero si todavía no llegó mercadería.',
    )
