# Email transaccional · Zoho Mail

Cómo está montado el correo `ventas@ideasboutique.cl` y cómo operarlo.
Configurado en junio 2026; probado end-to-end desde local y desde prod.

## Arquitectura

| Pieza | Valor |
|---|---|
| Proveedor | Zoho Mail (plan Mail Lite, datacenter US) |
| Casilla | `ventas@ideasboutique.cl` |
| SMTP | `smtp.zoho.com:587` STARTTLS (`smtp.zoho.eu` si la cuenta fuera EU) |
| Auth | **App password** (no la clave del webmail) — se genera en accounts.zoho.com → Seguridad → App Passwords (requiere 2FA) y es revocable individualmente |
| DNS | Gestionado en **Hetzner DNS Console** |
| Webmail | https://mail.zoho.com |

### Registros DNS (Hetzner)

| Tipo | Nombre | Contenido | Para qué |
|---|---|---|---|
| MX | `@` | `mx.zoho.com` (10), `mx2.zoho.com` (20), `mx3.zoho.com` (50) | Recibir correo |
| TXT | `@` | `v=spf1 include:zohomail.com ~all` | SPF — autoriza a Zoho a enviar por el dominio |
| TXT | `zmail._domainkey` | (clave DKIM generada por Zoho) | DKIM — firma criptográfica |
| TXT | `_dmarc` | `v=DMARC1; p=quarantine; ...` | DMARC — política anti-spoofing |

Verificación rápida desde PowerShell:

```powershell
Resolve-DnsName ideasboutique.cl -Type MX
Resolve-DnsName zmail._domainkey.ideasboutique.cl -Type TXT
Resolve-DnsName _dmarc.ideasboutique.cl -Type TXT
```

## Variables en `.env`

```env
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp.zoho.com
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_HOST_USER=ventas@ideasboutique.cl
EMAIL_HOST_PASSWORD=<app password de Zoho>
DEFAULT_FROM_EMAIL=Ideas Boutique <ventas@ideasboutique.cl>
SERVER_EMAIL=ventas@ideasboutique.cl
EMAIL_TIMEOUT=10
OWNER_NOTIFICATION_EMAIL=<correo del dueño para avisos de venta>
```

En dev se usa `EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend`
(los correos salen por la consola del runserver, no viajan).

## Emails que envía el sistema

| Email | Cuándo | Flag |
|---|---|---|
| Boleta de compra | Pedido online queda pagado | siempre |
| Aviso al dueño | Pedido online queda pagado | `OWNER_NOTIFICATION_EMAIL` |
| Aviso a despachadores | Pedido online queda pagado | rol `despachador` activo |
| Bienvenida | Registro de cliente | `FEATURE_EMAIL_BIENVENIDA` |
| Reset de password | Solicitud del cliente | `FEATURE_EMAIL_RESET_PASSWORD` |
| Volvió la talla | Reposición de stock con suscriptores — **un solo envío por suscripción**, con link de baja | `FEATURE_EMAIL_STOCK_DISPONIBLE` |
| Carrito abandonado | Programado (+24 h) — requiere cron | `FEATURE_EMAIL_CARRITO_ABANDONADO` |
| Pedir reseña | Programado (+14 días) — requiere cron | `FEATURE_EMAIL_PEDIR_RESENA` |
| Recordatorio familia | Anual (febrero, uniformes) — requiere cron | `FEATURE_EMAIL_RECORDATORIO_FAMILIA` |

## Probar / previsualizar

- **Preview en browser**: `/cuenta/emails/` (staff) — renderiza todos los
  templates con datos demo y permite enviarse una copia de prueba.
- **Shell**:
  ```python
  from django.core.mail import send_mail
  send_mail('Prueba', 'Cuerpo', None, ['destino@ejemplo.cl'])
  ```

## Troubleshooting

| Síntoma | Causa típica | Fix |
|---|---|---|
| `Authentication failed` | Usaste la clave del webmail | Generar app password |
| `Connection refused` | Host/puerto mal o cuenta en otro DC | Confirmar `smtp.zoho.com:587` (o `.eu`) |
| Cae a spam | DKIM/DMARC ausentes o rotos | Verificar los TXT de arriba |
| En prod no toma cambios de `.env` | gunicorn cachea el entorno | `restart-app` |

## Seguridad

- La app password vive SOLO en el `.env` del server (chmod 600). Si se
  filtra, revocarla en Zoho y generar otra — no afecta la clave principal.
- No compartir claves por chat; si pasó, revocar inmediatamente.
