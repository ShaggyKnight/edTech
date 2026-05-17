# Seguridad — Ideas Boutique 2.0

Runbook para el equipo técnico (Eduardo y futuros admins) sobre cómo
mantener segura la app en producción.

## Resumen del estado actual

| Capa | Mecanismo | Estado |
|---|---|---|
| SQL injection | Django ORM (sin `.raw()`, sin `.extra()`) | ✅ Cubierto |
| XSS | Auto-escape de templates + `|safe` mínimo y revisado | ✅ Cubierto |
| CSRF | `CsrfViewMiddleware` + `CSRF_TRUSTED_ORIGINS` | ✅ Cubierto |
| Sesiones | HTTPOnly + `Secure` + `SameSite=Lax` | ✅ Cubierto |
| HTTPS forzado | `SECURE_SSL_REDIRECT` + nginx | ✅ Cubierto |
| HSTS | `SECURE_HSTS_SECONDS=31536000` en prod | ⚙️ Setear en `.env` |
| Headers | X-Frame-Options DENY, Content-Type nosniff, Referrer-Policy | ✅ Cubierto |
| Fuerza bruta | django-axes (5 intentos → 1 h lockout) | ✅ Cubierto |
| Admin oculto | `ADMIN_URL` configurable | ⚙️ Setear en `.env` |
| Passwords | 4 validators de Django | ✅ Cubierto |
| Upload limits | 5 MB max para imágenes | ✅ Cubierto |
| Secretos | Solo en `.env`, nunca en código | ✅ Cubierto |
| Dependencias | `pip-audit` periódico | ⚙️ Recurrente |

---

## Variables de entorno OBLIGATORIAS en producción

Verificar antes del primer deploy:

```bash
DEBUG=False                                # NUNCA True en prod
SECRET_KEY=<50+ chars random>              # Generar con `python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"`
ALLOWED_HOSTS=ideasboutique.cl,www.ideasboutique.cl
DATABASE_URL=postgresql://user:pass@host/db
CSRF_TRUSTED_ORIGINS=https://ideasboutique.cl,https://www.ideasboutique.cl

# Hardening
ADMIN_URL=eduardo-blanca-x7k2/             # algo no-obvio, NO /admin/
ADMIN_EMAIL=eduardo.tapia.contreras@gmail.com
AXES_FAILURE_LIMIT=5
AXES_COOLOFF_HOURS=1
AXES_PROXY_COUNT=1                         # nginx delante: 1

# HTTPS (después del primer deploy estable)
SECURE_SSL_REDIRECT=False                  # nginx redirige primero
SECURE_HSTS_SECONDS=31536000               # 1 año

# Email (errores 500 + boletas)
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp.gmail.com                  # o el que uses
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_HOST_USER=ventas@ideasboutique.cl
EMAIL_HOST_PASSWORD=<app password>
DEFAULT_FROM_EMAIL=ventas@ideasboutique.cl
```

---

## Operación normal

### Crear superusuario

Solo Eduardo es superuser. Otros admins son `is_staff=True` pero **no superuser** (limita el daño si se compromete su cuenta).

```bash
python manage.py createsuperuser
# username: eduardo
# email: eduardo.tapia.contreras@gmail.com
# password: <generado con un gestor, no reutilizar>
```

Para admins adicionales (Blanca, futuro personal):

```bash
python manage.py shell
>>> from django.contrib.auth import get_user_model
>>> User = get_user_model()
>>> u = User.objects.create_user('blanca', email='blanca@...', password='...')
>>> u.is_staff = True
>>> u.save()
>>> # Asignar al grupo 'admin' para los permisos del backoffice:
>>> from django.contrib.auth.models import Group
>>> u.groups.add(Group.objects.get(name='admin'))
```

### Login bloqueado por axes (alguien me lockeó)

Si Eduardo o Blanca quedan bloqueados por intentos fallidos:

```bash
# Desbloquear todos los usuarios y IPs:
python manage.py axes_reset

# Desbloquear solo un usuario:
python manage.py axes_reset_username eduardo

# Desbloquear solo una IP:
python manage.py axes_reset_ip 192.168.1.100

# Ver intentos fallidos recientes:
python manage.py axes_list_attempts
```

### Rotar `SECRET_KEY`

Si sospechás compromiso:

1. Generar key nueva:
   ```python
   from django.core.management.utils import get_random_secret_key
   print(get_random_secret_key())
   ```
2. Reemplazar `SECRET_KEY` en `.env` del servidor.
3. Reiniciar gunicorn: `sudo systemctl restart ideas`.
4. **Consecuencia:** todas las sesiones activas quedan invalidadas (los clientes vuelven a `/cuenta/login/`). Esto es deseable post-incidente.

---

## Cuando sospechás un ataque

Síntomas:
- Picos de tráfico anormales en logs de nginx
- Múltiples 429 (axes lockout) en `django.request` log
- Emails 500 inesperados al ADMIN_EMAIL
- POSTs sospechosos a `/cuenta/login/`, `/{ADMIN_URL}/`, `/tienda/checkout/`

Pasos:

1. **No entrar en pánico.** Capturar evidencia primero, actuar después.
2. **Snapshot logs y db**:
   ```bash
   sudo journalctl -u ideas -n 1000 > /tmp/incidente-$(date +%F).log
   pg_dump ideas > /tmp/incidente-$(date +%F).sql
   ```
3. **Bloquear la IP atacante** en `ufw`:
   ```bash
   sudo ufw deny from <IP>
   ```
4. **Rotar `SECRET_KEY`** (ver arriba).
5. **Forzar cambio de password** a todos los staff:
   ```bash
   python manage.py shell
   >>> from django.contrib.auth import get_user_model
   >>> get_user_model().objects.filter(is_staff=True).update(password='!')
   # `!` = password inválido (nadie puede loguearse hasta resetear).
   ```
6. **Reportar** si hubo robo de datos de cliente (Ley 19.628 Chile).

---

## Backups

Crítico para el negocio. Sin backup, un attacker con acceso a DB puede borrar todo.

**Configurado en el VPS Hetzner** (ver `deploy/` del repo, sección Hetzner del README):
- `pg_dump` diario a las 03:00 América/Santiago
- Sube a Backblaze B2 (S3-compatible) con retención de 30 días
- Encriptación at-rest con `gpg --symmetric` antes del upload
- Restore probado mensualmente (cron job que loguea el resultado)

**Test de restore** (cada 30 días):
```bash
ssh ideas@vps "/srv/ideas/scripts/restore-test.sh"
# Debe terminar con: "RESTORE OK — 234 productos, 89 ventas"
```

Si el script falla > 1 vez, **abrir incidente**.

---

## Actualizaciones de dependencias

**Auditar mensualmente:**

```bash
cd /srv/ideas
source venv/bin/activate
pip install pip-audit
pip-audit -r requirements.txt
```

`pip-audit` lista CVEs conocidos en cada paquete. Si reporta vulnerabilidades:
- Critical / High → actualizar mismo día, redesplegar
- Medium → planificar dentro de la semana
- Low → next maintenance window

**Django security releases** (https://docs.djangoproject.com/en/dev/internals/security/):
- Suscribirse a `django-announce` mailing list
- Aplicar parches dentro de 7 días de release

---

## Lo que NO está cubierto (decisiones conscientes)

| Tema | Por qué no | Cómo mitigamos |
|---|---|---|
| WAF (Cloudflare/Caddy) | Costo + complejidad sin justificarse al volumen actual | nginx con rate limits básicos + django-axes |
| 2FA en admin | Aún no, Eduardo lo activará si el negocio crece | Password fuerte + axes + ADMIN_URL no-obvio |
| Content-Security-Policy strict | Conflicto con HTMX inline scripts + Alpine.js | X-Frame DENY + nosniff + Referrer-Policy |
| `django-axes` con Redis | Volumen actual no lo requiere | Default DB backend (axes_attempt table) |
| Penetration test externo | Aún no se justifica al volumen | `pip-audit` mensual + `manage.py check --deploy` |
| Cifrado de columnas (RUT, email) | Complejidad operacional | DB encrypted at-rest a nivel disco (Hetzner) |

Estos temas re-evaluar cuando el volumen mensual supere los 500 pedidos online.

---

## `manage.py check --deploy`

Antes de cada deploy en prod:

```bash
DEBUG=False python manage.py check --deploy
```

Debe pasar sin warnings. Si hay alguno, **NO desplegar** hasta resolverlo.

---

## Contactos en caso de incidente

- **Eduardo Tapia** (superuser) — eduardo.tapia.contreras@gmail.com
- **Blanca Contreras** (dueña, admin) — actualizar email
- **Hetzner support** — https://www.hetzner.com/support/
- **Reporte CSIRT Chile** (incidentes con robo de datos) — https://www.csirt.gob.cl/

---

_Última revisión: 2026-05-16. Próxima auditoría: 2026-08-16 (trimestral)._
