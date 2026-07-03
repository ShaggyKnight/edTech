"""Forms de gestión de usuarios staff para el backoffice.

Permiten al ADMIN crear y editar usuarios (cajero / bodeguero /
despachador / admin) sin entrar al Django admin. Cada usuario tiene
exactamente UN rol primario — al asignar uno se limpian los otros
role-groups.
"""
from __future__ import annotations

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.password_validation import validate_password

from .roles import ALL_ROLES

User = get_user_model()


# Etiquetas humanas para cada rol (el value es el name del Group).
ROL_LABELS = {
    'admin': 'Administrador — acceso total',
    'cajero': 'Cajero — POS y ventas',
    'bodeguero': 'Bodeguero — stock y catálogo',
    'despachador': 'Despachador — prepara y despacha pedidos online',
    'operador': 'Operador — tienda día a día: POS, despacho, stock, '
                'productos y ofertas (sin reportes ni materiales)',
}

ROL_CHOICES = [(r, ROL_LABELS.get(r, r.title())) for r in ALL_ROLES]


def _rol_actual(user) -> str:
    """Devuelve el primer rol del user (o '' si no tiene)."""
    nombres = set(user.groups.values_list('name', flat=True))
    for rol in ALL_ROLES:
        if rol in nombres:
            return rol
    return ''


def _set_rol(user, rol: str):
    """Asigna UN rol al user, quitando los demás role-groups.

    No toca grupos que no sean roles (por si en el futuro hay grupos
    de otra naturaleza).
    """
    # Quitar todos los role-groups actuales.
    role_groups = Group.objects.filter(name__in=ALL_ROLES)
    user.groups.remove(*role_groups)
    if rol:
        grupo, _ = Group.objects.get_or_create(name=rol)
        user.groups.add(grupo)


class _BaseUsuarioForm(forms.ModelForm):
    """Campos comunes de crear/editar."""
    rol = forms.ChoiceField(
        choices=ROL_CHOICES,
        label='Rol',
        widget=forms.Select(attrs={'class': 'bo-input'}),
    )
    recibe_notif_ecommerce = forms.BooleanField(
        required=False,
        initial=True,
        label='Recibe email de pedidos online',
        help_text='Solo aplica al rol Despachador. Apagalo para pausar '
                  'avisos sin desactivar la cuenta.',
    )

    class Meta:
        model = User
        fields = ('first_name', 'last_name', 'email', 'is_active')
        labels = {
            'first_name': 'Nombre',
            'last_name': 'Apellido',
            'email': 'Email',
            'is_active': 'Cuenta activa',
        }
        widgets = {
            'first_name': forms.TextInput(attrs={'class': 'bo-input'}),
            'last_name': forms.TextInput(attrs={'class': 'bo-input'}),
            'email': forms.EmailInput(attrs={'class': 'bo-input'}),
        }


class UsuarioCrearForm(_BaseUsuarioForm):
    """Crear un usuario staff nuevo."""
    username = forms.CharField(
        max_length=150,
        label='Nombre de usuario (para login)',
        help_text='Sin espacios. Ej: "blanca", "juan.perez".',
        widget=forms.TextInput(attrs={'class': 'bo-input', 'autocomplete': 'off'}),
    )
    password = forms.CharField(
        label='Contraseña inicial',
        widget=forms.PasswordInput(attrs={'class': 'bo-input', 'autocomplete': 'new-password'}),
        help_text='Comunícasela al empleado. Podrá cambiarla después.',
    )

    field_order = ['username', 'first_name', 'last_name', 'email',
                   'rol', 'password', 'is_active', 'recibe_notif_ecommerce']

    def clean_username(self):
        username = self.cleaned_data['username'].strip()
        if User.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError('Ese nombre de usuario ya existe.')
        return username

    def clean_password(self):
        pwd = self.cleaned_data['password']
        validate_password(pwd)
        return pwd

    def save(self, commit=True):
        user = super().save(commit=False)
        user.username = self.cleaned_data['username']
        user.set_password(self.cleaned_data['password'])
        user.is_staff = True   # todos los roles entran al backoffice
        if commit:
            user.save()
            _set_rol(user, self.cleaned_data['rol'])
            self._guardar_perfil(user)
        return user

    def _guardar_perfil(self, user):
        from .models import PerfilUsuario
        perfil, _ = PerfilUsuario.objects.get_or_create(usuario=user)
        perfil.recibe_notif_ecommerce = self.cleaned_data.get(
            'recibe_notif_ecommerce', True)
        perfil.save(update_fields=['recibe_notif_ecommerce'])


class UsuarioEditarForm(_BaseUsuarioForm):
    """Editar un usuario existente. No cambia username ni password
    (para eso hay una acción de reset aparte)."""

    field_order = ['first_name', 'last_name', 'email', 'rol',
                   'is_active', 'recibe_notif_ecommerce']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.fields['rol'].initial = _rol_actual(self.instance)
            try:
                self.fields['recibe_notif_ecommerce'].initial = \
                    self.instance.perfil.recibe_notif_ecommerce
            except Exception:
                self.fields['recibe_notif_ecommerce'].initial = True

    def clean_email(self):
        email = (self.cleaned_data.get('email') or '').strip()
        if email and User.objects.filter(email__iexact=email).exclude(
                pk=self.instance.pk).exists():
            raise forms.ValidationError(
                'Ese email ya está asociado a otra cuenta.')
        return email

    def save(self, commit=True):
        user = super().save(commit=commit)
        if commit:
            _set_rol(user, self.cleaned_data['rol'])
            from .models import PerfilUsuario
            perfil, _ = PerfilUsuario.objects.get_or_create(usuario=user)
            perfil.recibe_notif_ecommerce = self.cleaned_data.get(
                'recibe_notif_ecommerce', True)
            perfil.save(update_fields=['recibe_notif_ecommerce'])
        return user


class ResetPasswordForm(forms.Form):
    """Resetea la contraseña de un usuario staff."""
    password = forms.CharField(
        label='Nueva contraseña',
        widget=forms.PasswordInput(attrs={'class': 'bo-input', 'autocomplete': 'new-password'}),
    )

    def clean_password(self):
        pwd = self.cleaned_data['password']
        validate_password(pwd)
        return pwd
