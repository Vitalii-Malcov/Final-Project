from django.conf import settings
from django.db import models

from apps.core.models import UUIDv7Model


class ListingView(UUIDv7Model):
    """Один просмотр объявления: одна строка = один просмотр.

    Храним события, а не счётчик views += 1: так видно, кто и когда смотрел,
    а «популярность» считается агрегатом. Счётчик в самом Listing при
    параллельных запросах терял бы просмотры.
    """

    listing = models.ForeignKey('listings.Listing', on_delete=models.CASCADE, related_name='views')
    # Аноним тоже может смотреть -> null. SET_NULL: при удалении пользователя
    # просмотр остаётся в статистике, просто без автора.
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='listing_views',
    )
    viewed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'listing_views'

    def __str__(self):
        return f'{self.listing_id} @ {self.viewed_at:%Y-%m-%d %H:%M}'
