from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.mail import EmailMultiAlternatives
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.views.decorators.http import require_http_methods, require_POST

from .email_previews import PREVIEWS, get_preview
from .forms import (
    ROL_LABELS, ResetPasswordForm, UsuarioCrearForm, UsuarioEditarForm,
    _rol_actual,
)
from .roles import (
    ADMIN, ALL_ROLES, BODEGUERO, CAJERO, DESPACHADOR, OPERADOR, user_in_role,
)


def _es_staff(user):
    """Solo superusers o usuarios con rol ADMIN ven el preview."""
    return user.is_active and (user.is_superuser or user_in_role(user, ADMIN))


def _es_admin(user):
    """Gate para la gestión de usuarios — solo admin/superuser."""
    return user.is_active and (user.is_superuser or user_in_role(user, ADMIN))


@login_required
def dashboard(request):
    """Redirige al usuario a la pantalla principal según su rol.

    BUG-011: antes los usuarios sin rol staff veían un 403 "sin rol".
    Para los clientes de la tienda online el "dashboard" debe ser la
    lista de sus pedidos. La regla queda: si el usuario tiene rol staff
    (admin / cajero / bodeguero) entra al backoffice; cualquier otro
    usuario autenticado (cliente normal) cae en `/tienda/cuenta/pedidos/`.
    """
    user = request.user

    if user.is_superuser or user_in_role(user, ADMIN):
        return redirect(reverse('reportes:dashboard'))
    # Operador (operación completa simplificada): su día parte en el POS.
    if user_in_role(user, OPERADOR):
        return redirect(reverse('pos:home'))
    if user_in_role(user, CAJERO):
        return redirect(reverse('pos:home'))
    if user_in_role(user, BODEGUERO):
        return redirect(reverse('bodega:stock'))
    if user_in_role(user, DESPACHADOR):
        return redirect(reverse('despacho:cola'))

    # Cliente normal (sin rol staff) → su área de pedidos en la tienda.
    return redirect(reverse('ecommerce:mis_pedidos'))


# ─────────────────────────────────────────────────────────────────────
# Email preview — solo staff
# ─────────────────────────────────────────────────────────────────────
# Index en /cuenta/emails/ lista todos los emails con su mock data.
# Cada uno se previsualiza renderizando el template con data fake.
# Permite ademas reenviarse el email real (via SMTP de Zoho) para
# verificar como se ve en clientes (Gmail, Outlook, Apple Mail).

@user_passes_test(_es_staff, login_url='login')
def emails_index(request):
    """Lista de todos los emails transaccionales con preview."""
    items = []
    for entry in PREVIEWS:
        flag_estado = ''
        if entry.feature_flag:
            valor = getattr(settings, entry.feature_flag, False)
            flag_estado = 'on' if valor else 'off'
        items.append({
            'entry': entry,
            'flag_estado': flag_estado,
        })
    return render(request, 'accounts/emails_index.html', {
        'items': items,
        'site_url': getattr(settings, 'SITE_URL', '') or 'https://ideasboutique.cl',
    })


@user_passes_test(_es_staff, login_url='login')
def email_preview(request, slug):
    """Renderea un email con su mock data. La query `?raw=1` devuelve
    solo el HTML del email (util para abrir en iframe sin chrome)."""
    entry = get_preview(slug)
    if not entry:
        raise Http404(f'Email "{slug}" no esta registrado en email_previews.PREVIEWS')

    contexto = {
        **entry.contexto_fn(),
        # Globals que _enviar_multipart agrega siempre
        'PUBLIC_WHATSAPP': getattr(settings, 'PUBLIC_WHATSAPP', ''),
        'SITE_URL': getattr(settings, 'SITE_URL', '') or 'https://ideasboutique.cl',
    }

    try:
        html = render_to_string(entry.template, contexto)
    except Exception as exc:  # noqa: BLE001
        # Si el template tira error, devolvemos el mensaje para iterar
        # rapido en vez de un 500 silencioso.
        return HttpResponse(
            f'<h1>Error renderizando {entry.template}</h1>'
            f'<pre style="background:#fee;padding:20px;font-family:monospace;">{type(exc).__name__}: {exc}</pre>'
            f'<p><a href="{reverse("accounts:emails_index")}">← Volver</a></p>',
            status=500,
        )

    if request.GET.get('raw'):
        resp = HttpResponse(html)
        # El preview embebe esta respuesta en un <iframe> de la misma
        # pagina. X_FRAME_OPTIONS global es DENY (default de Django, y
        # explicito en prod) — sin este header el browser bloquea el
        # iframe y el preview se ve vacio. SAMEORIGIN solo permite
        # framearlo desde ideasboutique.cl, no desde sitios terceros.
        resp['X-Frame-Options'] = 'SAMEORIGIN'
        return resp

    return render(request, 'accounts/email_preview.html', {
        'entry': entry,
        'html_iframe_url': f'{reverse("accounts:email_preview", args=[slug])}?raw=1',
    })


@user_passes_test(_es_staff, login_url='login')
@require_POST
def email_enviar_demo(request, slug):
    """Renderea el email con mock data y lo manda al usuario logueado
    (o al email del form). Usa el SMTP real configurado en .env — para
    verificar como se ve en Gmail/Outlook/Apple Mail."""
    entry = get_preview(slug)
    if not entry:
        raise Http404()

    destinatario = (request.POST.get('email') or request.user.email or '').strip()
    if not destinatario:
        messages.error(request, 'No hay email destino. Indica uno o setea email en tu usuario.')
        return redirect('accounts:emails_index')

    contexto = {
        **entry.contexto_fn(),
        'PUBLIC_WHATSAPP': getattr(settings, 'PUBLIC_WHATSAPP', ''),
        'SITE_URL': getattr(settings, 'SITE_URL', '') or 'https://ideasboutique.cl',
    }

    try:
        html = render_to_string(entry.template, contexto)
        subject = f'[DEMO] {entry.subject_template}'
        msg = EmailMultiAlternatives(
            subject=subject,
            body=f'Demo del email "{entry.nombre}" — abrir en HTML.',
            from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', None),
            to=[destinatario],
        )
        msg.attach_alternative(html, 'text/html')
        msg.send(fail_silently=False)
        messages.success(
            request,
            f'Email "{entry.nombre}" enviado a {destinatario}. '
            f'Revisá la bandeja (puede tardar 10-30s).',
        )
    except Exception as exc:  # noqa: BLE001
        messages.error(request, f'Fallo al enviar: {type(exc).__name__}: {exc}')

    return redirect('accounts:emails_index')


# ─────────────────────────────────────────────────────────────────────
# Gestión de usuarios y roles — solo ADMIN (reemplaza el Django admin)
# ─────────────────────────────────────────────────────────────────────

@user_passes_test(_es_admin, login_url='login')
def usuarios_lista(request):
    """Lista todos los usuarios staff con su rol + estado."""
    User = get_user_model()
    # Solo usuarios staff (con rol). Los clientes de la tienda no se
    # gestionan acá — esos viven en el flujo de cuenta del ecommerce.
    usuarios = (
        User.objects
        .filter(groups__name__in=ALL_ROLES)
        .distinct()
        .select_related('perfil')
        .prefetch_related('groups')
        .order_by('-is_active', 'first_name', 'username')
    )

    filas = []
    for u in usuarios:
        rol = _rol_actual(u)
        try:
            notif = u.perfil.recibe_notif_ecommerce
        except Exception:
            notif = None
        filas.append({
            'u': u,
            'rol': rol,
            'rol_label': ROL_LABELS.get(rol, rol or '—'),
            'notif': notif,
            'es_despachador': rol == DESPACHADOR,
        })

    return render(request, 'accounts/usuarios_lista.html', {
        'filas': filas,
    })


@user_passes_test(_es_admin, login_url='login')
@require_http_methods(['GET', 'POST'])
def usuario_crear(request):
    """Crea un usuario staff nuevo con rol."""
    if request.method == 'POST':
        form = UsuarioCrearForm(request.POST)
        if form.is_valid():
            user = form.save()
            messages.success(
                request,
                f'Usuario "{user.username}" creado con rol '
                f'{ROL_LABELS.get(form.cleaned_data["rol"], "")}.',
            )
            return redirect('accounts:usuarios_lista')
    else:
        form = UsuarioCrearForm()

    return render(request, 'accounts/usuario_form.html', {
        'form': form,
        'modo': 'crear',
        'reset_form': None,
    })


@user_passes_test(_es_admin, login_url='login')
@require_http_methods(['GET', 'POST'])
def usuario_editar(request, pk):
    """Edita un usuario staff: rol, estado, notificaciones. La password
    se resetea con el form aparte (POST con accion=reset)."""
    User = get_user_model()
    usuario = get_object_or_404(User, pk=pk)

    form = UsuarioEditarForm(instance=usuario)
    reset_form = ResetPasswordForm()

    if request.method == 'POST':
        accion = request.POST.get('accion', 'editar')

        if accion == 'editar':
            form = UsuarioEditarForm(request.POST, instance=usuario)
            if form.is_valid():
                # Salvaguarda: el admin no puede auto-desactivarse ni
                # auto-quitarse el rol admin (evita lockout).
                if usuario.pk == request.user.pk:
                    if not form.cleaned_data.get('is_active', True):
                        messages.error(request, 'No podés desactivar tu propia cuenta.')
                        return redirect('accounts:usuario_editar', pk=pk)
                    if form.cleaned_data.get('rol') != ADMIN:
                        messages.error(request, 'No podés quitarte tu propio rol de administrador.')
                        return redirect('accounts:usuario_editar', pk=pk)
                form.save()
                messages.success(request, f'Usuario "{usuario.username}" actualizado.')
                return redirect('accounts:usuarios_lista')

        elif accion == 'reset':
            reset_form = ResetPasswordForm(request.POST)
            if reset_form.is_valid():
                usuario.set_password(reset_form.cleaned_data['password'])
                usuario.save(update_fields=['password'])
                messages.success(
                    request,
                    f'Contraseña de "{usuario.username}" reseteada. '
                    f'Comunícasela al empleado.',
                )
                return redirect('accounts:usuario_editar', pk=pk)

    return render(request, 'accounts/usuario_form.html', {
        'form': form,
        'reset_form': reset_form,
        'modo': 'editar',
        'usuario': usuario,
    })
