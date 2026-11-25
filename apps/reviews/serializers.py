from rest_framework import serializers

from apps.listings.serializers import OwnerSerializer
from apps.reviews.models import Review


class ReviewSerializer(serializers.ModelSerializer):
    """Чтение отзыва. Автор — id и имя, без email и телефона (отзывы публичные)."""

    author = OwnerSerializer(read_only=True)

    class Meta:
        model = Review
        fields = ('id', 'listing', 'author', 'rating', 'comment', 'created_at', 'updated_at')
        read_only_fields = fields


class ReviewCreateSerializer(serializers.ModelSerializer):
    """Создание отзыва: только оценка и текст.

    Объявление берётся из URL, автор — из токена, бронь находит view. Принимать их из тела
    нельзя: иначе можно было бы написать отзыв «от чужого имени» или на чужое жильё.
    Диапазон rating 1..5 берётся из валидаторов модели.
    """

    class Meta:
        model = Review
        fields = ('rating', 'comment')
        extra_kwargs = {'comment': {'max_length': 2000}}
