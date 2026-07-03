from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm
from django.db import models  # para Q en EditarPerfilForm


class AgregarForm(forms.Form):
    tipo = forms.ChoiceField(choices=[('v', 'variante'), ('p', 'producto')])
    item_id = forms.IntegerField(min_value=1)
    cantidad = forms.IntegerField(min_value=1, initial=1)


class ActualizarCantidadForm(forms.Form):
    key = forms.CharField(max_length=30)
    cantidad = forms.IntegerField(min_value=0)


class ResenaForm(forms.Form):
    """Form publico para que un cliente envie una resena de un producto.

    Bloque 9. Recibe `producto_id` como hidden + estrellas (1-5) +
    nombre publico + email (no se publica) + titulo (opcional) + texto.
    Valida que el email sea valido y que las estrellas esten en rango.
    La resena queda en estado `pendiente` hasta que la duena la apruebe.
    """
    producto_id = forms.IntegerField(min_value=1)
    estrellas = forms.IntegerField(min_value=1, max_value=5)
    titulo = forms.CharField(max_length=120, required=False, strip=True)
    texto = forms.CharField(
        widget=forms.Textarea(attrs={'rows': 4, 'maxlength': 2000}),
        min_length=10, max_length=2000, strip=True,
    )
    nombre_publico = forms.CharField(max_length=80, strip=True)
    cliente_email = forms.EmailField()


class CheckoutForm(forms.Form):
    """Datos del cliente en el checkout.

    El TELEFONO es el identificador de contacto principal (requerido):
    por ahi van los avisos de WhatsApp del pedido. El RUT se elimino del
    checkout — no emitimos factura y la boleta al consumidor no lo
    necesita. La direccion solo existe si FEATURE_ENVIOS esta activa;
    con la flag apagada la tienda opera solo con retiro en local.
    """
    cliente_nombre = forms.CharField(max_length=200)
    cliente_email = forms.EmailField()
    cliente_telefono = forms.CharField(max_length=20)
    cliente_direccion = forms.CharField(widget=forms.Textarea(attrs={'rows': 2}), required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from django.conf import settings
        if not getattr(settings, 'FEATURE_ENVIOS', False):
            # Sin envios no hay direccion que pedir NI aceptar — sacar el
            # campo evita que un POST manual meta una direccion que el
            # despacho interpretaria como "hay que enviar".
            self.fields.pop('cliente_direccion', None)

    def clean_cliente_telefono(self):
        """Normaliza a formato canonico +569XXXXXXXX.

        Acepta lo tipico: '+56 9 5544 3322', '9 5544 3322', '955443322',
        '56955443322'. Rechaza lo que no parezca celular chileno — es el
        canal de aviso del pedido (WhatsApp), tiene que servir.
        """
        import re
        crudo = self.cleaned_data.get('cliente_telefono', '')
        digitos = re.sub(r'\D', '', crudo)
        if digitos.startswith('56'):
            digitos = digitos[2:]
        if len(digitos) == 8:          # celular viejo sin el 9
            digitos = '9' + digitos
        if len(digitos) != 9 or not digitos.startswith('9'):
            raise forms.ValidationError(
                'Ingresa un celular chileno válido (ej: +56 9 5544 3322).'
            )
        return f'+56{digitos}'


class EditarPerfilForm(forms.ModelForm):
    """Form para que el cliente edite sus datos básicos desde
    `/tienda/cuenta/perfil/`.

    Edita: nombre (first_name), apellido (last_name), email (+ username
    espejo). No incluye contraseña — para eso se usa el flujo built-in
    `auth:password_change`. Tampoco incluye RUT/teléfono porque esos
    los pide el checkout y se guardan en el recibo, no en el User.

    Valida que el email NO esté tomado por otro user del sistema.
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
        fields = ('email', 'nombre', 'apellido')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Prepopulamos desde first_name/last_name de auth.User
        if self.instance and self.instance.pk:
            self.fields['nombre'].initial = self.instance.first_name
            self.fields['apellido'].initial = self.instance.last_name

    def clean_email(self):
        email = self.cleaned_data['email'].lower().strip()
        User = get_user_model()
        qs = User.objects.filter(
            models.Q(username__iexact=email) | models.Q(email__iexact=email)
        ).exclude(pk=self.instance.pk if self.instance else None)
        if qs.exists():
            raise forms.ValidationError(
                'Ese email ya está asociado a otra cuenta.',
            )
        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        # Email = username (mantener espejado con RegistroClienteForm)
        user.email = self.cleaned_data['email']
        user.username = self.cleaned_data['email']
        user.first_name = self.cleaned_data['nombre']
        user.last_name = self.cleaned_data.get('apellido', '')
        if commit:
            user.save()
        return user


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
