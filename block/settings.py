"""
Django settings for block project (BLOCK ERP powered by NOORSYS).
"""

from pathlib import Path

import environ
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DEBUG=(bool, True),
)
env_file = BASE_DIR / '.env'
if env_file.exists():
    environ.Env.read_env(env_file)

SECRET_KEY = env('SECRET_KEY', default='django-insecure-@^hb((ut^q6&1x@xeq+jrmk5plny*71f@%&o)9t!=uwfzg!22*')

DEBUG = env('DEBUG')


def _clean_hosts(hosts):
    """Tidy a hand-edited ALLOWED_HOSTS: ignore stray spaces/empties, reject URLs.

    django-environ keeps the space in "a.com, b.com", which would silently never match and
    show visitors a 400 error; a pasted "https://a.com" fails the same way.
    """
    cleaned = [host.strip() for host in hosts if host.strip()]
    for host in cleaned:
        if '://' in host or '/' in host:
            raise ImproperlyConfigured(
                f'ALLOWED_HOSTS entry {host!r} must be a bare domain such as example.com '
                '(no http(s):// and no path). Separate several with commas.'
            )
    return cleaned


ALLOWED_HOSTS = _clean_hosts(env.list('ALLOWED_HOSTS', default=['localhost', '127.0.0.1', 'asgroupbd.com',
        'daj.asgroupbd.com',
    'www.daj.asgroupbd.com',
]))


# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.humanize',

    # Block ERP apps
    'core',
    'customers',
    'suppliers',
    'projects',
    'costing',
    'sales',
    'books',
    'reports',
    'dashboard',
    'activity_log',

    # Third-party
    'crispy_forms',
    'crispy_bootstrap5',
]

CRISPY_ALLOWED_TEMPLATE_PACKS = 'bootstrap5'
CRISPY_TEMPLATE_PACK = 'bootstrap5'

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'block.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'core.context_processors.company',
            ],
        },
    },
]

WSGI_APPLICATION = 'block.wsgi.application'


# Database
# Defaults to SQLite for local dev. Set DATABASE_URL in the .env file to use another database.

if env('DATABASE_URL', default=None):
    DATABASES = {'default': env.db('DATABASE_URL')}
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }


# Password validation

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]


# Internationalization

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Asia/Dhaka'
USE_I18N = True
USE_TZ = True


# Static & media files

STATIC_URL = 'static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'

MEDIA_URL = 'media/'
MEDIA_ROOT = BASE_DIR / 'media'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

LOGIN_URL = 'login'
LOGIN_REDIRECT_URL = 'home'
LOGOUT_REDIRECT_URL = 'home'

MESSAGE_TAGS = {
    10: 'debug',
    20: 'info',
    25: 'success',
    30: 'warning',
    40: 'danger',
}

# Company identity — used across templates, printed documents and auto-numbering.
COMPANY_NAME = env('COMPANY_NAME', default='Block')
COMPANY_CODE_PREFIX = env('COMPANY_CODE_PREFIX', default='AB')
COMPANY_ADDRESS = env('COMPANY_ADDRESS', default='')
COMPANY_PHONE = env('COMPANY_PHONE', default='')
CURRENCY_SYMBOL = '৳'

# Email settings for password reset (configure via .env in production)
EMAIL_BACKEND = env('EMAIL_BACKEND', default='django.core.mail.backends.console.EmailBackend')
EMAIL_HOST = env('EMAIL_HOST', default='')
EMAIL_PORT = env.int('EMAIL_PORT', default=587)
EMAIL_USE_TLS = env.bool('EMAIL_USE_TLS', default=True)
EMAIL_HOST_USER = env('EMAIL_HOST_USER', default='')
EMAIL_HOST_PASSWORD = env('EMAIL_HOST_PASSWORD', default='')
DEFAULT_FROM_EMAIL = env('DEFAULT_FROM_EMAIL', default='Block ERP <noreply@example.com>')
