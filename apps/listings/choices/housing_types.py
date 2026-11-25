from django.db import models


class HousingType(models.TextChoices):
    APARTMENT = 'apartment', 'Квартира'
    HOUSE = 'house', 'Дом'
    STUDIO = 'studio', 'Студия'
    ROOM = 'room', 'Комната'
    TOWNHOUSE = 'townhouse', 'Таунхаус'
