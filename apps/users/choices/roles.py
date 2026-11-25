from django.db import models


class Role(models.TextChoices):
    """Роли пользователей.

    TextChoices: в БД лежит читаемая строка 'tenant' / 'landlord' (а не магическое число),
    при этом в коде пишем Role.TENANT — опечатка сразу видна, а не тихо ломает права.
    Второе значение в скобках — человекочитаемое имя для админки.
    """

    TENANT = 'tenant', 'Арендатор'
    LANDLORD = 'landlord', 'Арендодатель'
