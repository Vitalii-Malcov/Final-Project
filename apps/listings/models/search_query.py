from django.conf import settings
from django.db import models

from apps.core.models import UUIDv7Model


class SearchQuery(UUIDv7Model):
    """История поиска: одно ключевое слово = одна строка.

    «Популярные запросы» считаются как GROUP BY keyword + COUNT, поэтому по
    keyword нужен индекс. Слово хранится в нижнем регистре, чтобы «Berlin»
    и «berlin» попали в одну группу.
    """

    keyword = models.CharField(max_length=255, db_index=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='search_queries',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'search_history'
        ordering = ['-created_at']

    def __str__(self):
        return self.keyword
