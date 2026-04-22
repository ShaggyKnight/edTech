from django import forms


class AgregarForm(forms.Form):
    tipo = forms.ChoiceField(choices=[('v', 'variante'), ('p', 'producto')])
    item_id = forms.IntegerField(min_value=1)
    cantidad = forms.IntegerField(min_value=1, initial=1)


class ActualizarCantidadForm(forms.Form):
    key = forms.CharField(max_length=30)
    cantidad = forms.IntegerField(min_value=0)


class CheckoutForm(forms.Form):
    cliente_nombre = forms.CharField(max_length=200, required=False)
    cliente_email = forms.EmailField(required=False)
    cliente_rut = forms.CharField(max_length=20, required=False)
    dte_tipo = forms.IntegerField(required=False, min_value=0)


class SeleccionarTiendaForm(forms.Form):
    tienda_id = forms.IntegerField(min_value=1)
