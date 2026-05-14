from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm


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

    def clean_cliente_rut(self):
        """Valida el RUT con módulo 11. Si el cliente no lo ingresó
        (es opcional para boleta) no se valida."""
        rut = self.cleaned_data.get('cliente_rut', '').strip()
        if not rut:
            return ''
        from ecommerce.validators import validar_rut_chileno
        return validar_rut_chileno(rut)


class RegistroClienteForm(UserCreationForm):
    """Registro de cliente en la tienda.

    El email es el username: más natural para el comercio electrónico y se
    reutiliza para enlazar recibos creados como invitado antes del registro.
    """
    nombre = forms.CharField(
        max_length=150,
        label='Nombre',
        widget=forms.TextInput(attrs={'autocomplete': 'given-name'}),
    )
    apellido = forms.CharField(
        max_length=150,
        label='Apellido',
        required=False,
        widget=forms.TextInput(attrs={'autocomplete': 'family-name'}),
    )
    email = forms.EmailField(
        label='Email',
        widget=forms.EmailInput(attrs={'autocomplete': 'email'}),
    )

    class Meta:
        model = get_user_model()
        fields = ('email', 'nombre', 'apellido', 'password1', 'password2')

    def clean_email(self):
        email = self.cleaned_data['email'].lower().strip()
        User = get_user_model()
        if User.objects.filter(username__iexact=email).exists() or \
                User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError('Ya existe una cuenta con este email.')
        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        user.username = self.cleaned_data['email']
        user.email = self.cleaned_data['email']
        user.first_name = self.cleaned_data['nombre']
        user.last_name = self.cleaned_data.get('apellido', '')
        if commit:
            user.save()
        return user
