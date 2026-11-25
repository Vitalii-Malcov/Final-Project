from decimal import Decimal

from django.apps import apps
from django.conf import settings
from django.core.validators import MaxValueValidator, MinLengthValidator, MinValueValidator
from django.db import models
from django.db.models import Avg, Count, FloatField, IntegerField, OuterRef, Subquery
from django.db.models.functions import Coalesce

from apps.core.models import TimeStampedModel, UUIDv7Model
from apps.listings.choices.housing_types import HousingType


class ListingQuerySet(models.QuerySet):
    """Переиспользуемые «куски» запросов: Listing.objects.active().with_stats()."""

    def active(self):
        """Только видимые объявления (is_active=True)."""
        return self.filter(is_active=True)

    def with_stats(self):
        """Добавляет к каждому объявлению views_count, reviews_count, avg_rating.

        Почему Subquery, а не annotate(Count('views'), Count('reviews')):
        если одним запросом соединить (JOIN) и просмотры, и отзывы, строки
        перемножаются: 5 просмотров x 3 отзыва = 15 строк, и оба Count()
        вернут завышенные числа (приходится городить distinct=True, это
        медленно). Подзапросы считают каждую таблицу независимо, ничего
        не умножается, и сортировка по этим полям работает как обычная.

        Coalesce подставляет 0, когда у объявления нет ни просмотров, ни
        отзывов: подзапрос тогда вернул бы NULL, а он ломает сортировку и JSON.

        Модели берём через apps.get_model в момент вызова: если импортировать
        Review на уровне модуля, listings и reviews импортируют друг друга
        и получается циклический импорт.
        """
        ListingView = apps.get_model('listings', 'ListingView')
        Review = apps.get_model('reviews', 'Review')

        views = (
            ListingView.objects.filter(listing=OuterRef('pk'))
            .order_by()                 # сбрасываем ordering модели, иначе он попадёт в GROUP BY
            .values('listing')          # группировка по объявлению
            .annotate(c=Count('pk'))
            .values('c')
        )
        reviews = (
            Review.objects.filter(listing=OuterRef('pk'))
            .order_by()
            .values('listing')
            .annotate(c=Count('pk'))
            .values('c')
        )
        rating = (
            Review.objects.filter(listing=OuterRef('pk'))
            .order_by()
            .values('listing')
            .annotate(a=Avg('rating'))
            .values('a')
        )
        return self.annotate(
            views_count=Coalesce(Subquery(views, output_field=IntegerField()), 0),
            reviews_count=Coalesce(Subquery(reviews, output_field=IntegerField()), 0),
            avg_rating=Coalesce(Subquery(rating, output_field=FloatField()), 0.0, output_field=FloatField()),
        )


class Listing(UUIDv7Model, TimeStampedModel):
    """Объявление о сдаче жилья."""

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,   # нет арендодателя -> нет его объявлений
        related_name='listings',
    )
    title = models.CharField(max_length=200, validators=[MinLengthValidator(5)])
    description = models.TextField(validators=[MinLengthValidator(20)])
    city = models.CharField(max_length=100, db_index=True)  # по городу фильтруют чаще всего
    district = models.CharField(max_length=100, blank=True)
    address = models.CharField(max_length=255)
    # Деньги — DecimalField, не FloatField: float хранит 0.1 приблизительно
    # (0.1 + 0.2 = 0.30000000000000004), а в счетах копейки должны сходиться точно.
    price = models.DecimalField(
        max_digits=10, decimal_places=2,
        validators=[MinValueValidator(Decimal('1'))],
        help_text='Цена за ночь',
    )
    rooms = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(50)])
    housing_type = models.CharField(max_length=16, choices=HousingType.choices)
    is_active = models.BooleanField(default=True)

    objects = ListingQuerySet.as_manager()

    class Meta:
        db_table = 'listings'
        ordering = ['-created_at']
        indexes = [
            # Составные индексы под реальные запросы: «активные, отсортированные/
            # отфильтрованные по цене (или комнатам)». is_active стоит первым, потому
            # что по нему фильтруют всегда.
            models.Index(fields=['is_active', 'price']),
            models.Index(fields=['is_active', 'rooms']),
            models.Index(fields=['housing_type']),
        ]

    def __str__(self):
        return f'{self.title} ({self.city})'
