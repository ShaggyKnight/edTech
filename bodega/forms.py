"""Formularios de gestión de catálogo desde la pantalla de bodega.

Estos forms son la versión "operativa" del Django admin: pensados para
que el bodeguero/admin del negocio (no el superusuario que toca SQL)
pueda crear y editar productos, variantes y materiales sin entrar a
/admin/.
"""
from __future__ import annotations

from django import forms
from django.core.exceptions import ValidationError

from bodega.models import Material, Proveedor, Rendimiento
from catalogo.models import (
    Atributo,
    Colegio,
    Familia,
    Oferta,
    Producto,
    ProductoVariante,
    ValorAtributo,
)


# Atributos que tienen sentido en un selector de variante. Si más adelante
# se agregan "Color" o "Tipo", se listan acá. El form solo muestra los que
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
            'codigo_barras',
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
            'codigo_barras': forms.TextInput(attrs={
                'class': 'bo-input',
                'placeholder': 'EAN-13 de fábrica o "Generar" para uno interno',
                'pattern': r'[0-9]{0,32}',
                'maxlength': '32',
                'inputmode': 'numeric',
            }),
            'imagen': forms.ClearableFileInput(),
        }
        help_texts = {
            'colegio': 'Solo si es uniforme escolar (lleva insignia bordada).',
            'tiene_variantes': 'Marca si el producto se vende por talla, volumen, etc. '
                               'En el siguiente paso defines las variantes.',
            'precio_costo': 'Costo unitario. Sirve para calcular margen y valorizar inventario.',
            'codigo_barras': 'Solo aplica si NO tiene variantes. Para productos con '
                             'variantes, el código vive en cada variante. Si está '
                             'vacío se genera automáticamente al guardar.',
        }

    def save(self, commit=True):
        """Autogenera el codigo si no tiene variantes y quedó vacio."""
        from catalogo.barcode import generar_codigo_interno
        instance = super().save(commit=False)
        if commit:
            instance.save()
            # Si es producto sin variantes y no tiene codigo, generar uno.
            if not instance.tiene_variantes and not instance.codigo_barras:
                instance.codigo_barras = generar_codigo_interno('p', instance.pk)
                instance.save(update_fields=['codigo_barras'])
        return instance


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

        # SKU es opcional: si queda vacio, se autogenera en save() desde
        # marca + nombre del producto + valores seleccionados.
        if 'sku' in self.fields:
            self.fields['sku'].required = False

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
        fields = ['sku', 'precio_override', 'activa', 'codigo_barras']
        widgets = {
            'sku': forms.TextInput(attrs={'class': 'bo-input'}),
            'precio_override': forms.NumberInput(attrs={'class': 'bo-input', 'min': 0}),
            'activa': forms.CheckboxInput(),
            'codigo_barras': forms.TextInput(attrs={
                'class': 'bo-input',
                'placeholder': 'Vacío = generar automático',
                'pattern': r'[0-9]{0,32}',
                'maxlength': '32',
                'inputmode': 'numeric',
            }),
        }
        help_texts = {
            'sku': 'Código único. Vacío = se genera automático desde '
                   'marca + nombre + valores (ej. YARA-LATTAFA-100ML-EDP).',
            'precio_override': 'Si esta variante tiene precio distinto al producto base. '
                               'Vacío = usa el precio del producto.',
            'codigo_barras': 'Si la variante tiene EAN-13 de fábrica, ingresalo. '
                             'Vacío = se genera uno interno automáticamente.',
        }

    def save(self, commit=True, producto=None):
        from catalogo.barcode import generar_codigo_interno
        from catalogo.sku import sugerir_desde_variante
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
            # Autogenerar SKU si quedó vacío. Hace falta el M2M de valores
            # ya guardado, por eso va despues del v.valores.add().
            if not v.sku:
                v.sku = sugerir_desde_variante(v)
            # Autogenerar codigo de barras si quedó vacio (también necesita pk).
            if not v.codigo_barras:
                v.codigo_barras = generar_codigo_interno('v', v.pk)
            v.save(update_fields=['sku', 'codigo_barras'])
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


class MaterialForm(forms.ModelForm):
    """Crea o edita un Material (rollo de tela, accesorios, etc)."""

    class Meta:
        model = Material
        fields = [
            'nombre', 'descripcion', 'proveedor',
            'costo_unitario_referencia', 'activo',
        ]
        widgets = {
            'nombre': forms.TextInput(attrs={'class': 'bo-input'}),
            'descripcion': forms.Textarea(attrs={'class': 'bo-textarea', 'rows': 3}),
            'proveedor': forms.Select(attrs={'class': 'bo-select'}),
            'costo_unitario_referencia': forms.NumberInput(attrs={'class': 'bo-input', 'min': 0}),
            'activo': forms.CheckboxInput(),
        }
        help_texts = {
            'nombre': 'Nombre identificable. Ej: "Tela franela silvia (buzos SFJ)".',
            'descripcion': 'Descripción técnica del material — color, peso, uso.',
            'costo_unitario_referencia': 'Costo aproximado por rollo. Cada compra registra '
                                          'su costo real exacto en MovimientoMaterial.',
        }


class OfertaForm(forms.ModelForm):
    """Crea o edita una Oferta (descuento aplicado a producto o variante).

    Validaciones:
    - Debe seleccionarse producto o variante (al menos uno).
    - Si se elige variante y producto, la variante debe pertenecer al
      producto. En cualquier caso si hay variante, el producto se ignora
      (la oferta queda anclada a la variante).
    - valor > 0. Si tipo=Porcentaje, valor <= 100.
    - fecha_fin posterior a fecha_inicio.
    """

    class Meta:
        model = Oferta
        fields = [
            'nombre', 'producto', 'variante', 'tipo', 'valor',
            'canal', 'fecha_inicio', 'fecha_fin', 'activa',
        ]
        widgets = {
            'nombre': forms.TextInput(attrs={'class': 'bo-input'}),
            'producto': forms.Select(attrs={'class': 'bo-select'}),
            'variante': forms.Select(attrs={'class': 'bo-select'}),
            'tipo': forms.Select(attrs={'class': 'bo-select'}),
            'valor': forms.NumberInput(attrs={'class': 'bo-input', 'min': '0', 'step': '0.01'}),
            'canal': forms.Select(attrs={'class': 'bo-select'}),
            'fecha_inicio': forms.DateTimeInput(
                attrs={'class': 'bo-input', 'type': 'datetime-local'},
                format='%Y-%m-%dT%H:%M',
            ),
            'fecha_fin': forms.DateTimeInput(
                attrs={'class': 'bo-input', 'type': 'datetime-local'},
                format='%Y-%m-%dT%H:%M',
            ),
            'activa': forms.CheckboxInput(),
        }
        help_texts = {
            'nombre': 'Identificable. Ej. "Black Friday 2026", "SFJ uniforme -10%".',
            'producto': 'Aplica a todas las variantes del producto. Vacío si la oferta es por variante específica.',
            'variante': 'Solo si la oferta aplica a una variante puntual (ej. solo el Yara 30 ml). Si eliges variante, ignora el producto de arriba.',
            'valor': 'Si tipo=Porcentaje: 0-100. Si tipo=Monto fijo: pesos a descontar.',
            'canal': 'Donde aplica: solo en la tienda fisica, solo online, o en ambos.',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['producto'].queryset = (
            Producto.objects.filter(activo=True)
            .select_related('familia')
            .order_by('familia__nombre', 'nombre')
        )
        self.fields['producto'].required = False
        self.fields['variante'].queryset = (
            ProductoVariante.objects
            .filter(activa=True, producto__activo=True)
            .select_related('producto')
            .order_by('producto__nombre', 'sku')
        )
        self.fields['variante'].required = False
        # `size > 1` convierte el <select> en un listbox visible: las
        # opciones filtradas por el buscador se ven al instante, sin
        # tener que abrir el dropdown. El buscador anterior usaba
        # `option.hidden` adentro de un select cerrado, que no se
        # respetaba en todos los browsers.
        self.fields['producto'].widget.attrs.update({
            'size': 8, 'class': 'bo-input bo-listbox',
        })
        self.fields['variante'].widget.attrs.update({
            'size': 8, 'class': 'bo-input bo-listbox',
        })
        self.fields['fecha_inicio'].input_formats = ['%Y-%m-%dT%H:%M', '%Y-%m-%d %H:%M:%S']
        self.fields['fecha_fin'].input_formats = ['%Y-%m-%dT%H:%M', '%Y-%m-%d %H:%M:%S']

    def clean(self):
        cleaned = super().clean()
        producto = cleaned.get('producto')
        variante = cleaned.get('variante')

        if not producto and not variante:
            raise ValidationError(
                'Tenés que elegir un producto o una variante específica.'
            )
        if producto and variante and variante.producto_id != producto.pk:
            raise ValidationError(
                f'La variante {variante.sku} no pertenece al producto {producto.nombre}.'
            )
        # Si la oferta es por variante, el producto queda en None — la
        # variante ya determina a qué producto pertenece.
        if variante:
            cleaned['producto'] = None

        tipo = cleaned.get('tipo')
        valor = cleaned.get('valor')
        if valor is not None and valor <= 0:
            self.add_error('valor', 'Tiene que ser mayor a 0.')
        if tipo == Oferta.TIPO_PORCENTAJE and valor is not None and valor > 100:
            self.add_error('valor', 'El porcentaje no puede ser mayor a 100.')

        fi = cleaned.get('fecha_inicio')
        ff = cleaned.get('fecha_fin')
        if fi and ff and ff <= fi:
            self.add_error('fecha_fin', 'Tiene que ser posterior a la fecha de inicio.')

        return cleaned


class RendimientoForm(forms.ModelForm):
    """Crea o edita un Rendimiento (cuántas unidades de una variante salen
    de un rollo de cierto material)."""

    class Meta:
        model = Rendimiento
        fields = ['variante', 'unidades_por_rollo']
        widgets = {
            'variante': forms.Select(attrs={'class': 'bo-select'}),
            'unidades_por_rollo': forms.NumberInput(attrs={'class': 'bo-input', 'min': 1}),
        }
        help_texts = {
            'variante': 'A qué variante de producto se le aplica este rendimiento.',
            'unidades_por_rollo': 'Cuántas unidades de esa variante salen de un rollo.',
        }

    def __init__(self, *args, material=None, **kwargs):
        super().__init__(*args, **kwargs)
        # Solo variantes activas, ordenadas por producto.
        self.fields['variante'].queryset = (
            ProductoVariante.objects
            .filter(activa=True, producto__activo=True)
            .select_related('producto')
            .order_by('producto__nombre', 'sku')
        )
        self.material = material

    def save(self, commit=True):
        rend = super().save(commit=False)
        if self.material:
            rend.material = self.material
        if commit:
            rend.save()
        return rend
