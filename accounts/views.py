from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.mail import EmailMultiAlternatives
from django.http import Http404, HttpResponse
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.views.decorators.http import require_POST

from .email_previews import PREVIEWS, get_preview
from .roles import ADMIN, BODEGUERO, CAJERO, DESPACHADOR, user_in_role


def _es_staff(user):
    """Solo superusers o usuarios con rol ADMIN ven el preview."""
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
        return HttpResponse(html)

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
