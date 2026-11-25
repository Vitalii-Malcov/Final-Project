from django.apps import AppConfig


class UsersConfig(AppConfig):
    # Полный путь: приложение лежит внутри пакета apps/, поэтому не просто 'users'.
    # Без этого Django не найдёт модуль и выдаст ModuleNotFoundError.
    name = 'apps.users'
