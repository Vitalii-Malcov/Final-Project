from django.apps import AppConfig


class BookingsConfig(AppConfig):
    # Полный путь: приложение лежит внутри пакета apps/, поэтому не просто 'bookings'.
    # Без этого Django не найдёт модуль и выдаст ModuleNotFoundError.
    name = 'apps.bookings'
