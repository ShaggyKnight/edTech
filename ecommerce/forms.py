from django import forms


class AgregarForm(forms.Form):
    tipo = forms.ChoiceField(choices=[('v', 'variante'), ('p', 'producto')])
    item_id = forms.IntegerField(min_value=1)
    cantidad = forms.IntegerField(min_value=1, initial=1)


class ActualizarCantidadForm(forms.Form):
    key = forms.CharField(max_length=30)
    cantidad = forms.IntegerField(min_value=0)


class CheckoutForm(forms.Form):
    cliente_nombre = forms.CharField(max_length=200)
    cliente_email = forms.EmailField()
    cliente_rut = forms.CharField(max_length=20, required=False)
    cliente_telefono = forms.CharField(max_length=20, required=False)
    cliente_direccion = forms.CharField(widget=forms.Textarea(attrs={'rows': 2}), required=False)
