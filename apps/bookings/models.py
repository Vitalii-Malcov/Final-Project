from datetime import timedelta

from django.conf import settings
from django.db import models
from django.db.models import F, Q
from django.utils import timezone

from apps.bookings.choices.statuses import BookingStatus
from apps.core.models import TimeStampedModel, UUIDv7Model


class BookingQuerySet(models.QuerySet):
    def overlapping(self, start_date, end_date):
        """Брони, пересекающиеся с периодом [start_date, end_date).

        Два периода пересекаются, когда каждый начинается раньше конца другого:
            существующая.start < новый.end  И  существующая.end > новый.start
        Сравнения строгие: выезд 10-го и заезд 10-го в тот же день не конфликт,
        ведь ночуют люди не одновременно.
        """
        return self.filter(start_date__lt=end_date, end_date__gt=start_date)

    def active(self):
        """Текущие и будущие: ожидает или подтверждено, и ещё не закончились."""
        return self.filter(
            status__in=[BookingStatus.PENDING, BookingStatus.CONFIRMED],
            end_date__gt=timezone.localdate(),  # localdate: «сегодня» по Берлину, а не по UTC
        )

    def completed(self):
        """Прошедшие: подтверждённые, выезд наступил. Только по ним можно писать отзыв."""
        return self.filter(status=BookingStatus.CONFIRMED, end_date__lte=timezone.localdate())


class Booking(UUIDv7Model, TimeStampedModel):
    """Бронь жилья на период [start_date, end_date): end_date — день выезда."""

    listing = models.ForeignKey('listings.Listing', on_delete=models.CASCADE, related_name='bookings')
    tenant = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='bookings')
    start_date = models.DateField()
    end_date = models.DateField()
    # Цена ФИКСИРУЕТСЯ в момент брони (price x ночей). Если арендодатель потом
    # поднимет цену объявления, договорённая сумма у арендатора не изменится.
    total_price = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(max_length=16, choices=BookingStatus.choices, default=BookingStatus.PENDING)

    objects = BookingQuerySet.as_manager()

    class Meta:
        db_table = 'bookings'
        ordering = ['-created_at']
        constraints = [
            # Защита на уровне БД: даже если в сериализаторе забудут проверку,
            # бронь с выездом раньше заезда в таблицу не попадёт.
            models.CheckConstraint(
                condition=Q(end_date__gt=F('start_date')),
                name='booking_end_after_start',
            ),
        ]
        indexes = [
            models.Index(fields=['listing', 'status']),  # поиск пересечений по объявлению
            models.Index(fields=['tenant', 'status']),   # «мои брони»
        ]

    def __str__(self):
        return f'{self.listing_id}: {self.start_date} - {self.end_date} ({self.status})'

    @property
    def nights(self):
        return (self.end_date - self.start_date).days

    @property
    def cancellation_deadline(self):
        """Последняя дата, когда ещё можно отменить: заезд минус N дней (из .env)."""
        return self.start_date - timedelta(days=settings.BOOKING_CANCELLATION_DEADLINE_DAYS)

    @property
    def is_completed(self):
        return self.status == BookingStatus.CONFIRMED and self.end_date <= timezone.localdate()
