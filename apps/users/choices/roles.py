from django.db import models


class Role(models.TextChoices):
    """Имена групп-ролей.

    Роль в проекте — это стандартная группа django.contrib.auth.models.Group с таким именем.
    Здесь храним ТОЛЬКО имена (константы), а сами права группам выдаёт миграция
    users/0002_create_role_groups. Пользователь может состоять в обеих группах сразу.

    TextChoices удобен тем, что список допустимых значений (Role.values) и подписи
    (Role.choices) лежат в одном месте: ими пользуются сериализаторы и админка.
    """

    TENANT = 'tenant', 'Арендатор'
    LANDLORD = 'landlord', 'Арендодатель'
