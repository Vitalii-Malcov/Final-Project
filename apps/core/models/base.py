import uuid

from django.db import models


class UUIDv7Model(models.Model):
    """Абстрактная модель: первичный ключ — UUID версии 7.

    Почему UUID, а не 1, 2, 3...:
      * по URL нельзя перебрать чужие записи (/bookings/1/, /bookings/2/...);
      * id можно сгенерировать до записи в БД.
    Почему именно v7, а не v4: v7 начинается с временной метки, поэтому новые
    ключи растут по возрастанию. В InnoDB (MySQL) первичный ключ — это ещё и
    порядок хранения строк, и случайные v4 раскидывают вставки по всему
    индексу, а v7 дописываются в конец. uuid.uuid7 появился в Python 3.14.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)

    class Meta:
        abstract = True  # своей таблицы нет: поля копируются в наследников


class TimeStampedModel(models.Model):
    """Абстрактная модель: когда запись создана и когда последний раз менялась."""

    created_at = models.DateTimeField(auto_now_add=True)  # ставится один раз при создании
    updated_at = models.DateTimeField(auto_now=True)      # обновляется при каждом save()

    class Meta:
        abstract = True
