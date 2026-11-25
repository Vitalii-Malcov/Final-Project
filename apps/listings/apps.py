from django.apps import AppConfig


class ListingsConfig(AppConfig):
    # Полный путь: приложение лежит внутри пакета apps/, поэтому не просто 'listings'.
    # Без этого Django не найдёт модуль и выдаст ModuleNotFoundError.
    name = 'apps.listings'
