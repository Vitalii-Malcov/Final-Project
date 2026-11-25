from django.apps import AppConfig


class ReviewsConfig(AppConfig):
    # Полный путь: приложение лежит внутри пакета apps/, поэтому не просто 'reviews'.
    # Без этого Django не найдёт модуль и выдаст ModuleNotFoundError.
    name = 'apps.reviews'
