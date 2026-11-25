from django.db import models


class BookingStatus(models.TextChoices):
    PENDING = 'pending', 'Ожидает подтверждения'
    CONFIRMED = 'confirmed', 'Подтверждено'
    REJECTED = 'rejected', 'Отклонено арендодателем'
    CANCELLED = 'cancelled', 'Отменено арендатором'
