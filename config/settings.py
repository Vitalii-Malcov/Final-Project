from datetime import timedelta
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent

# django-environ читает переменные из .env и приводит типы (bool, list, int).
# Секреты и пароли живут только в .env, в git попадает лишь .env.example.
env = environ.Env()
environ.Env.read_env(BASE_DIR / '.env')

SECRET_KEY = env('SECRET_KEY')
DEBUG = env.bool('DEBUG', default=False)  # безопасный дефолт: на сервере забыли -> выключено
ALLOWED_HOSTS = env.list('ALLOWED_HOSTS', default=[])
# Для Django 4+ при HTTPS/доменах нужен список доверенных origin (используем на AWS).
CSRF_TRUSTED_ORIGINS = env.list('CSRF_TRUSTED_ORIGINS', default=[])

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    # Сторонние
    'rest_framework',
    'rest_framework_simplejwt.token_blacklist',  # таблицы для чёрного списка refresh-токенов (logout)
    # Наши приложения (полный путь, т.к. лежат в пакете apps/)
    'apps.core',
    'apps.users',
    'apps.listings',
    'apps.bookings',
    'apps.reviews',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    # WhiteNoise раздаёт статику (админка) из gunicorn без nginx; обязан идти сразу после Security.
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    # Наш JWT-страж — последним: к этому моменту остальные middleware уже отработали.
    'apps.core.middleware.JWTProtectedRoutesMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

# --- База данных -------------------------------------------------------------
# MYSQL=True -> основная MySQL (требование задания), False -> SQLite для быстрых проверок.
if env.bool('MYSQL', default=True):
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.mysql',
            'NAME': env('MYSQL_DATABASE'),
            'USER': env('MYSQL_USER'),
            'PASSWORD': env('MYSQL_PASSWORD'),
            'HOST': env('MYSQL_HOST', default='127.0.0.1'),
            'PORT': env('MYSQL_PORT', default='3306'),
            'OPTIONS': {
                'charset': 'utf8mb4',  # полноценный UTF-8 (кириллица, эмодзи в отзывах)
                'init_command': "SET sql_mode='STRICT_TRANS_TABLES'",  # ошибка вместо тихого обрезания данных
            },
        }
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }

# Своя модель пользователя. Указывать ДО первого migrate: потом сменить без боли нельзя.
AUTH_USER_MODEL = 'users.User'

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# --- Язык и время ------------------------------------------------------------
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Europe/Berlin'  # объявления по Германии; "сегодня" для броней считается по Берлину
USE_I18N = True
USE_TZ = True  # в БД время хранится в UTC, наружу отдаётся с часовым поясом

# --- Статика -----------------------------------------------------------------
STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'  # сюда collectstatic собирает файлы в Docker

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'  # для служебных таблиц (blacklist и т.п.)

# --- DRF и JWT ---------------------------------------------------------------
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ],
    # По умолчанию всё закрыто; публичные эндпоинты явно открываем через AllowAny.
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_PAGINATION_CLASS': 'apps.core.pagination.DefaultPagination',
    # Только JSON: браузерный интерфейс DRF не нужен, тестируем через Postman.
    'DEFAULT_RENDERER_CLASSES': [
        'rest_framework.renderers.JSONRenderer',
    ],
}

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=30),   # короткий: украденный токен быстро протухнет
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
    'ROTATE_REFRESH_TOKENS': True,        # каждый refresh выдаёт новый refresh-токен
    'BLACKLIST_AFTER_ROTATION': True,     # а старый сразу попадает в чёрный список
    'AUTH_HEADER_TYPES': ('Bearer',),
}

# Срок отмены брони: не позже чем за N дней до заезда.
BOOKING_CANCELLATION_DEADLINE_DAYS = env.int('BOOKING_CANCELLATION_DEADLINE_DAYS', default=1)
