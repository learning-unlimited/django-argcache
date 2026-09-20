import os
TESTS_DIR = os.path.dirname(__file__)

SECRET_KEY = 'abc'

INSTALLED_APPS = [
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'argcache.apps.ArgCacheConfig',
    'tests',
]

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': os.path.join(TESTS_DIR, 'db.sqlite3'),
    }
}

ROOT_URLCONF = 'argcache.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'OPTIONS': {
            'loaders': [
                'django.template.loaders.app_directories.Loader',
            ]
        }
    }
]

MIDDLEWARE = [
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
]

DEFAULT_AUTO_FIELD = 'django.db.models.AutoField'

# Set ARGCACHE_TEST_MEMCACHED to a memcached address (host:port) to run the
# suite against it. The default locmem backend only warns about keys that
# memcached can't store; the memcached backends reject them outright.
MEMCACHED_LOCATION = os.environ.get('ARGCACHE_TEST_MEMCACHED')
if MEMCACHED_LOCATION:
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.memcached.PyMemcacheCache',
            'LOCATION': MEMCACHED_LOCATION,
        }
    }
