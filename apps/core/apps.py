from django.apps import AppConfig


class CoreConfig(AppConfig):
    # Полный путь: приложение лежит внутри пакета apps/, поэтому не просто 'core'.
    # Без этого Django не найдёт модуль и выдаст ModuleNotFoundError.
    name = 'apps.core'
