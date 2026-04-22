"""
Django settings for edTech project (Ideas 2.0).
"""

from pathlib import Path
import environ

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DEBUG=(bool, False),
    ALLOWED_HOSTS=(list, ['localhost', '127.0.0.1']),
    LANGUAGE_CODE=(str, 'es-CL'),
    TIME_ZONE=(str, 'America/Santiago'),
    PAYMENT_GATEWAY=(str, 'mock'),
    TUU_API_KEY=(str, ''),
    TUU_DEVICE_SERIAL=(str, ''),
    TUU_BASE_URL=(str, 'https://integrations.payment.haulmer.com'),
    TUU_DTE_TIPO=(str, '39'),
    ECOMMERCE_PAYMENT_GATEWAY=(str, 'mock'),
    ECOMMERCE_TIENDA_ID=(int, 0),
    WEBPAY_COMMERCE_CODE=(str, ''),
    WEBPAY_API_KEY=(str, ''),
    WEBPAY_BASE_URL=(str, 'https://webpay3gint.transbank.cl'),
    DEFAULT_FROM_EMAIL=(str, 'ventas@ideas.local'),
    EMAIL_BACKEND=(str, 'django.core.mail.backends.console.EmailBackend'),
)
environ.Env.read_env(BASE_DIR / '.env')

SECRET_KEY = env('SECRET_KEY')
DEBUG = env('DEBUG')
ALLOWED_HOSTS = env('ALLOWED_HOSTS')

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.humanize',
    'rest_framework',
    'accounts.apps.AccountsConfig',
    'catalogo.apps.CatalogoConfig',
    'bodega.apps.BodegaConfig',
    'pos.apps.PosConfig',
    'ecommerce.apps.EcommerceConfig',
    'contabilidad.apps.ContabilidadConfig',
    'reportes.apps.ReportesConfig',
]

LOGIN_URL = 'login'
LOGIN_REDIRECT_URL = 'accounts:dashboard'
LOGOUT_REDIRECT_URL = 'login'

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
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

STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'edTech' / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Pagos POS (TUU / Haulmer). Usar gateway 'mock' en dev.
PAYMENT_GATEWAY = env('PAYMENT_GATEWAY')
TUU_API_KEY = env('TUU_API_KEY')
TUU_DEVICE_SERIAL = env('TUU_DEVICE_SERIAL')
TUU_BASE_URL = env('TUU_BASE_URL')
TUU_DTE_TIPO = env('TUU_DTE_TIPO')

# Pagos ecommerce (Webpay / Transbank). Usar gateway 'mock' en dev.
ECOMMERCE_PAYMENT_GATEWAY = env('ECOMMERCE_PAYMENT_GATEWAY')
# pk de bodega.Tienda que surte el canal online (0 = sin configurar)
ECOMMERCE_TIENDA_ID = env('ECOMMERCE_TIENDA_ID') or None
WEBPAY_COMMERCE_CODE = env('WEBPAY_COMMERCE_CODE')
WEBPAY_API_KEY = env('WEBPAY_API_KEY')
WEBPAY_BASE_URL = env('WEBPAY_BASE_URL')

# Email (boleta al cliente online). Por defecto console backend en dev.
EMAIL_BACKEND = env('EMAIL_BACKEND')
DEFAULT_FROM_EMAIL = env('DEFAULT_FROM_EMAIL')
