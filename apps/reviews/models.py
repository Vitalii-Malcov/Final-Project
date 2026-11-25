from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q

from apps.core.models import TimeStampedModel, UUIDv7Model


class Review(UUIDv7Model, TimeStampedModel):
    """Отзыв и оценка арендатора об объявлении."""

    listing = models.ForeignKey('listings.Listing', on_delete=models.CASCADE, related_name='reviews')
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='reviews')
    # Бронь, на основании которой оставлен отзыв (доказательство, что человек
    # реально жил). OneToOne: одна бронь = максимум один отзыв.
    booking = models.OneToOneField(
        'bookings.Booking', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='review',
    )
    rating = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    comment = models.TextField()

    class Meta:
        db_table = 'reviews'
        ordering = ['-created_at']
        constraints = [
            # Один человек - один отзыв на объявление (правило держит сама БД, а не только код).
            models.UniqueConstraint(fields=['listing', 'author'], name='unique_review_per_listing_author'),
            models.CheckConstraint(condition=Q(rating__gte=1, rating__lte=5), name='review_rating_1_5'),
        ]

    def __str__(self):
        return f'{self.listing_id}: {self.rating}/5 by {self.author_id}'
