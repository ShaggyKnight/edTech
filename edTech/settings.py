"""
Django settings for edTech project (Ideas 2.0).
"""

import sys
from pathlib import Path
import environ

BASE_DIR = Path(__file__).resolve().parent.parent

# `python manage.py test` setea sys.argv[1] = 'test'. Lo detectamos
# para apagar django-axes durante la suite: AxesBackend requiere el
# objeto `request` en authenticate() y `Client.login()` no lo pasa.
TESTING = 'test' in sys.argv

env = environ.Env(
    DEBUG=(bool, False),
    ALLOWED_HOSTS=(list, ['localhost', '127.0.0.1']),
    CSRF_TRUSTED_ORIGINS=(list, []),
    LANGUAGE_CODE=(str, 'es-CL'),
    TIME_ZONE=(str, 'America/Santiago'),
    SECURE_SSL_REDIRECT=(bool, False),
    SECURE_HSTS_SECONDS=(int, 0),
    USE_WHITENOISE=(bool, True),
    LOG_LEVEL=(str, 'INFO'),
    PAYMENT_GATEWAY=(str, 'mock'),
    TUU_API_KEY=(str, ''),
    TUU_DEVICE_SERIAL=(str, ''),
    TUU_BASE_URL=(str, 'https://integrations.payment.haulmer.com'),
    TUU_DTE_TIPO=(str, '39'),
    # Antiguo: un solo gateway online. Reemplazado por la lista
    # ECOMMERCE_GATEWAYS_ACTIVOS. Se mantiene como alias retrocompat —
    # si se setea, se considera como el unico activo.
    ECOMMERCE_PAYMENT_GATEWAY=(str, ''),
    ECOMMERCE_TIENDA_ID=(int, 0),
    # Multi-gateway: lista CSV de gateways habilitados (`klap`, `khipu`,
    # `mock`). El primero es el default si no se especifica otro.
    ECOMMERCE_GATEWAYS_ACTIVOS=(list, ['mock']),
    ECOMMERCE_GATEWAY_DEFAULT=(str, ''),
    # KLAP (tarjeta credito/debito) — pasarela KLAP/Multicaja.
    KLAP_COMMERCE_ID=(str, ''),
    KLAP_API_KEY=(str, ''),
    KLAP_WEBHOOK_SECRET=(str, ''),
    KLAP_BASE_URL=(str, 'https://sandbox.klap.cl'),
    # Khipu (transferencia bancaria) — comision mas baja.
    KHIPU_RECEIVER_ID=(str, ''),
    KHIPU_SECRET=(str, ''),
    KHIPU_BASE_URL=(str, 'https://payment-api.khipu.com'),
    DEFAULT_FROM_EMAIL=(str, 'ventas@ideas.local'),
    EMAIL_BACKEND=(str, 'django.core.mail.backends.console.EmailBackend'),
    # SMTP — solo necesarios si EMAIL_BACKEND apunta a smtp.EmailBackend.
    # Defaults pensados para Zoho Mail (datacenter US). Si tu cuenta es EU,
    # cambialo a `smtp.zoho.eu` en el .env.
    EMAIL_HOST=(str, 'smtp.zoho.com'),
    EMAIL_PORT=(int, 587),
    EMAIL_USE_TLS=(bool, True),
    EMAIL_HOST_USER=(str, ''),
    EMAIL_HOST_PASSWORD=(str, ''),
    # SERVER_EMAIL: de donde salen los mails automaticos de Django (alertas
    # de error a ADMINS cuando DEBUG=False). Si esta vacio, usa
    # DEFAULT_FROM_EMAIL.
    SERVER_EMAIL=(str, ''),
    # Timeout en segundos para abrir el socket SMTP. Sin esto, un Zoho
    # caido haria que `send_mail()` cuelgue al request hasta que el SO
    # corte. 10s es razonable para SMTP transactional.
    EMAIL_TIMEOUT=(int, 10),
    DTE_EMISSOR=(str, 'mock'),
    OPENFACTURA_API_KEY=(str, ''),
    OPENFACTURA_BASE_URL=(str, 'https://api.haulmer.com'),
    OPENFACTURA_RUT_EMISOR=(str, ''),
    # Lista de canales (separados por coma) que SI generan boleta SII.
    # Estrategia: arrancamos solo con online. Cuando la tienda fisica este
    # operativa y la maquina TUU integrada, agregar `presencial` al .env.
    # Mientras esta vacio, los recibos del canal NO emiten DTE — pasan
    # por todo el flujo de venta pero sin folio SII.
    DTE_CANALES_HABILITADOS=(list, ['online']),
    # Sprint 3 · SEO + ops (opcionales, no-op si vacíos).
    SITE_URL=(str, ''),
    OWNER_NOTIFICATION_EMAIL=(str, ''),
    ANALYTICS_DOMAIN=(str, ''),
    # Microsoft Clarity project ID — heatmaps + session replays.
    # Vacio en dev/local = sin tracking. En prod se setea en .env.
    CLARITY_PROJECT_ID=(str, ''),
    # BUG-009: número de WhatsApp del local. Formato E.164 sin + ni
    # espacios (ej. '56912345678'). Vacío = el bloque "WhatsApp directo"
    # se muestra como texto plano (estado actual hasta que se configure).
    PUBLIC_WHATSAPP=(str, ''),
    # Feature flags publicas. Bloque 9 quedo apagado por default hasta
    # que la duena tenga banda para moderar las resenas. La data
    # (model + admin + tests) se mantiene — solo se oculta el UI.
    FEATURE_RESENAS=(bool, False),
    # Feature flags de emails transaccionales. Todos arrancan apagados
    # hasta que la duena haya validado los templates con envios manuales
    # y se monten los cron/celery para los programados. Activar uno a
    # uno conforme se prueben.
    FEATURE_EMAIL_BIENVENIDA=(bool, False),
    FEATURE_EMAIL_RESET_PASSWORD=(bool, False),
    FEATURE_EMAIL_STOCK_DISPONIBLE=(bool, False),
    FEATURE_EMAIL_CARRITO_ABANDONADO=(bool, False),
    FEATURE_EMAIL_PEDIR_RESENA=(bool, False),
    FEATURE_EMAIL_RECORDATORIO_FAMILIA=(bool, False),
    # Hardening (ver SECURITY.md). En dev quedan en defaults seguros;
    # en prod el .env los redefine.
    ADMIN_URL=(str, 'admin/'),          # Cambiar en prod por path no-obvio
    ADMIN_EMAIL=(str, ''),              # Email del superusuario (recibe 500s)
    AXES_FAILURE_LIMIT=(int, 5),        # 5 intentos fallidos = lockout
    AXES_COOLOFF_HOURS=(int, 1),        # 1 hora de bloqueo
    # Paths de artifactos generados (collectstatic) y subidos (admin).
    # En dev quedan adentro del repo. En prod el .env los apunta FUERA
    # del checkout de git para que `git pull` no los toque.
    STATIC_ROOT=(str, ''),
    MEDIA_ROOT=(str, ''),
)
environ.Env.read_env(BASE_DIR / '.env')

SECRET_KEY = env('SECRET_KEY')
DEBUG = env('DEBUG')
ALLOWED_HOSTS = env('ALLOWED_HOSTS')
# En prod con HTTPS + dominio, ej: CSRF_TRUSTED_ORIGINS=https://ideas.cl,https://www.ideas.cl
CSRF_TRUSTED_ORIGINS = env('CSRF_TRUSTED_ORIGINS')

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.humanize',
    'django.contrib.sitemaps',
    'rest_framework',
    # Anti-fuerza-bruta para /admin/ y /cuenta/login/.
    'axes',
    'accounts.apps.AccountsConfig',
    'catalogo.apps.CatalogoConfig',
    'bodega.apps.BodegaConfig',
    'pos.apps.PosConfig',
    'ecommerce.apps.EcommerceConfig',
    'contabilidad.apps.ContabilidadConfig',
    'reportes.apps.ReportesConfig',
    'despacho.apps.DespachoConfig',
]

LOGIN_URL = 'login'
LOGIN_REDIRECT_URL = 'accounts:dashboard'
LOGOUT_REDIRECT_URL = 'login'

USE_WHITENOISE = env('USE_WHITENOISE')

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    # WhiteNoise sirve static files en prod sin necesidad de nginx/CDN.
    # Se inserta justo después de SecurityMiddleware (documentación oficial).
    *(['whitenoise.middleware.WhiteNoiseMiddleware'] if USE_WHITENOISE else []),
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    # Marca request.htmx para que views/templates puedan ajustar su salida.
    'edTech.middleware.HtmxMiddleware',
    # Modo mantenimiento: si existe el archivo MAINTENANCE_FLAG_FILE, el
    # publico ve una pagina de "volvemos pronto" (HTTP 503). Staff/admin
    # siguen viendo todo. Va DESPUES de Auth + Htmx para tener `request.user`.
    'edTech.middleware.MaintenanceMiddleware',
    # django-axes: debe ir AL FINAL para ver el resultado del login.
    'axes.middleware.AxesMiddleware',
]

# Archivos flag para los modos del sitio. Crear/borrar estos archivos
# enciende y apaga los modos sin necesidad de reiniciar gunicorn.
# Defaults dentro de BASE_DIR para que `runserver` local funcione sin
# .env; en prod el .env los apunta a /srv/ideas/ (fuera del checkout).
#
#   - MAINTENANCE: pagina "Volvemos pronto" (503) en todo el sitio.
#   - LANDING_ONLY: solo la home (`/`) y `/info/` quedan publicas;
#     el resto redirige a `/`. Util para soft-launch.
#
# Si ambos archivos existen, MAINTENANCE gana.
MAINTENANCE_FLAG_FILE = env('MAINTENANCE_FLAG_FILE', default=str(BASE_DIR / 'MAINTENANCE'))
LANDING_ONLY_FLAG_FILE = env('LANDING_ONLY_FLAG_FILE', default=str(BASE_DIR / 'LANDING_ONLY'))

# Auth backends: AxesStandaloneBackend RECHAZA logins de IPs/usuarios
# bloqueados antes de llegar al ModelBackend. No autentica por si solo —
# solo gatea. El orden importa: axes primero.
AUTHENTICATION_BACKENDS = [
    'axes.backends.AxesStandaloneBackend',
    'django.contrib.auth.backends.ModelBackend',
]

ROOT_URLCONF = 'edTech.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'edTech' / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'edTech.context_processors.public_settings',
            ],
        },
    },
]

WSGI_APPLICATION = 'edTech.wsgi.application'

DATABASES = {
    'default': env.db('DATABASE_URL', default=f'sqlite:///{BASE_DIR / "db.sqlite3"}'),
}

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = env('LANGUAGE_CODE')
TIME_ZONE = env('TIME_ZONE')
USE_I18N = True
USE_TZ = True

# Formato de fechas chileno: DD-MM-AAAA. Aplica al filtro {{ fecha }}
# sin parametro y a varios widgets de formularios. Los templates con
# `|date:"..."` explicito quedan como esten — pero la convencion del
# proyecto es usar el mismo formato (`d-m-Y` o `d-m-Y H:i`).
DATE_FORMAT = 'd-m-Y'
DATETIME_FORMAT = 'd-m-Y H:i'
SHORT_DATE_FORMAT = 'd-m-Y'
SHORT_DATETIME_FORMAT = 'd-m-Y H:i'

STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'edTech' / 'static']
# STATIC_ROOT y MEDIA_ROOT son configurables via env para que en prod
# vivan FUERA del checkout de git (/srv/ideas/staticfiles, /srv/ideas/media).
# Asi `git reset --hard` u otros deploys no tocan los archivos generados
# por collectstatic ni las imagenes subidas por el admin.
# Default = dentro del proyecto, util para `runserver` local sin .env.
STATIC_ROOT = Path(env('STATIC_ROOT')) if env('STATIC_ROOT') else BASE_DIR / 'staticfiles'

# En prod con WhiteNoise usamos el storage con manifest (hash + compresión).
# Sin WhiteNoise Django sirve staticfiles "crudos" y no hay que forzar el storage.
if USE_WHITENOISE and not DEBUG:
    STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

MEDIA_URL = '/media/'
MEDIA_ROOT = Path(env('MEDIA_ROOT')) if env('MEDIA_ROOT') else BASE_DIR / 'media'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'


# --- Limites de upload (DoS hardening) ------------------------------------
# Las imagenes de producto rondan 200-800 KB. Cap en 5 MB cubre con holgura
# y bloquea uploads abusivos que podrian llenar /media o saturar memoria.
DATA_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024   # 5 MB
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024   # 5 MB


# --- Cookies y sesion (siempre activas, no solo en prod) ------------------
SESSION_COOKIE_HTTPONLY = True   # JS no puede leer la cookie de sesion
CSRF_COOKIE_HTTPONLY = False     # JS si necesita leer el CSRF para AJAX
SESSION_COOKIE_SAMESITE = 'Lax'  # Bloquea CSRF cross-site sin romper login OAuth
CSRF_COOKIE_SAMESITE = 'Lax'


# --- Seguridad de producción ----------------------------------------------
# Todo lo que sigue sólo tiene efecto cuando DEBUG=False. En dev queda inerte
# para no romper el runserver ni Django admin local sobre http.
if not DEBUG:
    # Detrás de un proxy (nginx, Railway, Fly, Heroku router) que termina TLS.
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

    # Redirige http→https salvo que lo deshabilites explícitamente en el env.
    # Esto permite desplegar en un host que ya hace redirect en el edge sin
    # causar loops (por ejemplo, Fly.io con `force_https`).
    SECURE_SSL_REDIRECT = env('SECURE_SSL_REDIRECT')

    # HSTS: 0 por defecto para el primer deploy; aumentar a 31536000 (1 año)
    # cuando el dominio esté estable. Incluir subdominios y preload sólo
    # cuando confirmes que todos viven en HTTPS.
    SECURE_HSTS_SECONDS = env('SECURE_HSTS_SECONDS')
    SECURE_HSTS_INCLUDE_SUBDOMAINS = SECURE_HSTS_SECONDS > 0
    SECURE_HSTS_PRELOAD = SECURE_HSTS_SECONDS > 0

    # Cookies sólo por HTTPS.
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

    # Hardening adicional.
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_REFERRER_POLICY = 'same-origin'
    X_FRAME_OPTIONS = 'DENY'


# --- Logging --------------------------------------------------------------
# Salida estructurada a stderr para que el runtime (systemd, Docker, Railway)
# la capture. Apps de Ideas 2.0 logean al namespace de Django.
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'default': {
            'format': '{levelname} {asctime} {name} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'default',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': env('LOG_LEVEL'),
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'level': env('LOG_LEVEL'),
            'propagate': False,
        },
        'django.request': {
            'handlers': ['console'],
            'level': 'WARNING',
            'propagate': False,
        },
    },
}

# Pagos POS (TUU / Haulmer). Usar gateway 'mock' en dev.
PAYMENT_GATEWAY = env('PAYMENT_GATEWAY')
TUU_API_KEY = env('TUU_API_KEY')
TUU_DEVICE_SERIAL = env('TUU_DEVICE_SERIAL')
TUU_BASE_URL = env('TUU_BASE_URL')
TUU_DTE_TIPO = env('TUU_DTE_TIPO')

# Pagos ecommerce (Webpay / Transbank). Usar gateway 'mock' en dev.
ECOMMERCE_PAYMENT_GATEWAY = env('ECOMMERCE_PAYMENT_GATEWAY')
ECOMMERCE_GATEWAYS_ACTIVOS = env('ECOMMERCE_GATEWAYS_ACTIVOS')
ECOMMERCE_GATEWAY_DEFAULT = env('ECOMMERCE_GATEWAY_DEFAULT')
# Si esta seteado el viejo ECOMMERCE_PAYMENT_GATEWAY (singular), lo
# usamos como unico gateway activo (retrocompat con .env preexistentes).
if ECOMMERCE_PAYMENT_GATEWAY:
    ECOMMERCE_GATEWAYS_ACTIVOS = [ECOMMERCE_PAYMENT_GATEWAY]
    ECOMMERCE_GATEWAY_DEFAULT = ECOMMERCE_PAYMENT_GATEWAY

# KLAP — pasarela tarjetas
KLAP_COMMERCE_ID = env('KLAP_COMMERCE_ID')
KLAP_API_KEY = env('KLAP_API_KEY')
KLAP_WEBHOOK_SECRET = env('KLAP_WEBHOOK_SECRET')
KLAP_BASE_URL = env('KLAP_BASE_URL')

# Khipu — transferencia bancaria
KHIPU_RECEIVER_ID = env('KHIPU_RECEIVER_ID')
KHIPU_SECRET = env('KHIPU_SECRET')
KHIPU_BASE_URL = env('KHIPU_BASE_URL')
# pk de bodega.Tienda que surte el canal online (0 = sin configurar)
ECOMMERCE_TIENDA_ID = env('ECOMMERCE_TIENDA_ID') or None
# Webpay (Transbank) — removido del codigo en commit 2026-05-21. Si en
# el futuro se vuelve a integrar Webpay como alternativa, agregar el
# adapter en ecommerce/gateways/webpay.py y registrar en _REGISTRY.

# Email (boleta al cliente online). Por defecto console backend en dev.
# En prod (Hetzner VPS) usamos SMTP de Zoho — ver .env.example seccion email.
EMAIL_BACKEND = env('EMAIL_BACKEND')
DEFAULT_FROM_EMAIL = env('DEFAULT_FROM_EMAIL')
EMAIL_HOST = env('EMAIL_HOST')
EMAIL_PORT = env('EMAIL_PORT')
EMAIL_USE_TLS = env('EMAIL_USE_TLS')
EMAIL_HOST_USER = env('EMAIL_HOST_USER')
EMAIL_HOST_PASSWORD = env('EMAIL_HOST_PASSWORD')
EMAIL_TIMEOUT = env('EMAIL_TIMEOUT')
# Si no se setea SERVER_EMAIL en .env, cae al DEFAULT_FROM_EMAIL.
SERVER_EMAIL = env('SERVER_EMAIL') or DEFAULT_FROM_EMAIL

# Emisión de boleta/factura electrónica al SII (DTE).
# Opciones: mock | openfactura | none | ruta.modulo.ClaseEmissor
DTE_EMISSOR = env('DTE_EMISSOR')
OPENFACTURA_API_KEY = env('OPENFACTURA_API_KEY')
OPENFACTURA_BASE_URL = env('OPENFACTURA_BASE_URL')
OPENFACTURA_RUT_EMISOR = env('OPENFACTURA_RUT_EMISOR')
# Canales habilitados para emision SII. Hoy solo `online` — la tienda
# fisica + POS presencial NO emite hasta que se integre TUU.
DTE_CANALES_HABILITADOS = env('DTE_CANALES_HABILITADOS')

# Sprint 3 · 3.5/3.9 — SEO + notificaciones + analytics.
SITE_URL = env('SITE_URL')                              # ej: https://ideasboutique.cl
OWNER_NOTIFICATION_EMAIL = env('OWNER_NOTIFICATION_EMAIL')  # email de Blanca
ANALYTICS_DOMAIN = env('ANALYTICS_DOMAIN')              # dominio Plausible (vacío = sin analytics)
CLARITY_PROJECT_ID = env('CLARITY_PROJECT_ID')          # Microsoft Clarity (vacío = sin heatmaps)
PUBLIC_WHATSAPP = env('PUBLIC_WHATSAPP')                # BUG-009: WhatsApp del local, ej '56912345678'

# Feature flags. Bloque 9 (resenas) sigue codeado y testeado pero
# se oculta en la UI publica hasta que la duena tenga ancho de banda
# para moderar. Se prende cambiando FEATURE_RESENAS=True en .env.
FEATURE_RESENAS = env('FEATURE_RESENAS')
# Emails transaccionales — apagados por default.
FEATURE_EMAIL_BIENVENIDA = env('FEATURE_EMAIL_BIENVENIDA')
FEATURE_EMAIL_RESET_PASSWORD = env('FEATURE_EMAIL_RESET_PASSWORD')
FEATURE_EMAIL_STOCK_DISPONIBLE = env('FEATURE_EMAIL_STOCK_DISPONIBLE')
FEATURE_EMAIL_CARRITO_ABANDONADO = env('FEATURE_EMAIL_CARRITO_ABANDONADO')
FEATURE_EMAIL_PEDIR_RESENA = env('FEATURE_EMAIL_PEDIR_RESENA')
FEATURE_EMAIL_RECORDATORIO_FAMILIA = env('FEATURE_EMAIL_RECORDATORIO_FAMILIA')


# --- Hardening de autenticacion y exposicion ----------------------------
# Path del Django admin. En dev queda `admin/` por convencion; en prod el
# .env lo cambia a algo no-obvio (ej. `eduardo-admin/`) para que los bots
# que escanean /admin/wp-admin/login.php se pierdan.
ADMIN_URL = env('ADMIN_URL').lstrip('/')
if not ADMIN_URL.endswith('/'):
    ADMIN_URL += '/'

# Email del superusuario. Recibe el reporte de errores 500 (Django arma
# email automaticamente cuando DEBUG=False — ver ADMINS + handler
# `django.utils.log.AdminEmailHandler`).
_admin_email = env('ADMIN_EMAIL')
ADMINS = [('Eduardo Tapia', _admin_email)] if _admin_email else []
MANAGERS = ADMINS

# django-axes: lockout tras intentos fallidos de login.
# Defaults conservadores: 5 intentos por usuario+IP, lockout de 1 hora.
# El admin se desbloquea automaticamente despues del cooloff.
AXES_FAILURE_LIMIT = env('AXES_FAILURE_LIMIT')
AXES_COOLOFF_TIME = env('AXES_COOLOFF_HOURS')   # en horas (int) — axes lo entiende
AXES_LOCKOUT_PARAMETERS = ['username', 'ip_address']
AXES_RESET_ON_SUCCESS = True
AXES_ENABLE_ADMIN = True
# IPs que NO se bloquean (LAN del local). Vacio = todos. En prod podemos
# whitelistear la IP de la tienda fisica si genera mucho falso-positivo.
AXES_NEVER_LOCKOUT_WHITELIST = False
# Para sitios detras de un reverse proxy (nginx, Cloudflare): usar el
# X-Forwarded-For real, no la IP del proxy. AxesMiddleware respeta esto
# si lo configuramos con la lista de proxies confiables. En dev queda
# vacio; en prod (ver .env.example) se setea con la IP del balanceador.
# En axes 7+ la opcion vive bajo el namespace `ipware` (django-axes usa
# la lib django-ipware internamente). El nombre viejo `AXES_PROXY_COUNT`
# imprime un warning de deprecacion al arrancar.
AXES_IPWARE_PROXY_COUNT = env.int('AXES_PROXY_COUNT', default=0)
# Apagar axes durante la suite de tests: el Client.login() de Django no
# pasa el `request` que AxesBackend exige. Cada test que quiera probar
# el lockout puede usar `@override_settings(AXES_ENABLED=True)` o el
# cliente real (POST a /cuenta/login/). Ver tests/test_axes_lockout.py.
AXES_ENABLED = not TESTING
