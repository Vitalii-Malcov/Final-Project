from rest_framework import serializers

from apps.listings.choices.housing_types import HousingType
from apps.listings.models import SearchQuery

# Что пользователь пишет в ?ordering= -> по какому полю (аннотации) сортируем.
# Список закрытый (белый): произвольное имя поля от клиента в order_by() подставлять нельзя.
# Минус перед именем = по убыванию, как в Django.
ORDERING_FIELDS = {
    'price': 'price',
    'created_at': 'created_at',
    'views': 'views_count',      # аннотация из with_stats()
    'reviews': 'reviews_count',  # аннотация из with_stats()
    'rating': 'avg_rating',      # аннотация из with_stats()
}
ORDERING_CHOICES = list(ORDERING_FIELDS) + [f'-{name}' for name in ORDERING_FIELDS]
DEFAULT_ORDERING = '-created_at'  # новые объявления первыми


class ListingFilterSerializer(serializers.Serializer):
    """Проверка query-параметров GET /listings/.

    Использование во view:
        f = ListingFilterSerializer(data=request.query_params)
        f.is_valid(raise_exception=True)   # любая ошибка -> 400 с описанием
        params = f.validated_data

    Зачем отдельный сериализатор, а не request.query_params.get(...) прямо во view:
    все параметры приходят строками, и без проверки ?price_min=abc дал бы 500
    (ValueError) или молча отфильтровал бы по мусору. Здесь тип, диапазон и
    допустимые значения проверяются в одном месте, а клиент получает 400 с
    понятным текстом.
    """

    # allow_blank=True: «?search=» (пустая строка) трактуем как «параметр не задан».
    search = serializers.CharField(required=False, allow_blank=True, max_length=100)
    price_min = serializers.DecimalField(required=False, max_digits=10, decimal_places=2, min_value=0)
    price_max = serializers.DecimalField(required=False, max_digits=10, decimal_places=2, min_value=0)
    city = serializers.CharField(required=False, allow_blank=True, max_length=100)
    district = serializers.CharField(required=False, allow_blank=True, max_length=100)
    rooms_min = serializers.IntegerField(required=False, min_value=1, max_value=50)
    rooms_max = serializers.IntegerField(required=False, min_value=1, max_value=50)
    # Приходит строкой «apartment,house», превращаем в список в validate_housing_type.
    housing_type = serializers.CharField(required=False, allow_blank=True)
    ordering = serializers.ChoiceField(required=False, choices=ORDERING_CHOICES, default=DEFAULT_ORDERING)

    def validate_housing_type(self, value):
        # Разбиваем по запятой, чистим пробелы и регистр, убираем дубли (порядок сохраняем).
        requested = list(dict.fromkeys(
            part.strip().lower() for part in value.split(',') if part.strip()
        ))
        invalid = [item for item in requested if item not in HousingType.values]
        if invalid:
            raise serializers.ValidationError(
                f'Invalid housing type(s): {", ".join(invalid)}. '
                f'Allowed: {", ".join(HousingType.values)}.'
            )
        return requested  # список допустимых значений, может быть пустым

    def validate(self, attrs):
        # Межполевые проверки: диапазон не может быть «перевёрнутым».
        errors = {}
        if 'price_min' in attrs and 'price_max' in attrs and attrs['price_min'] > attrs['price_max']:
            errors['price_min'] = 'price_min must not be greater than price_max.'
        if 'rooms_min' in attrs and 'rooms_max' in attrs and attrs['rooms_min'] > attrs['rooms_max']:
            errors['rooms_min'] = 'rooms_min must not be greater than rooms_max.'
        if errors:
            raise serializers.ValidationError(errors)

        # Готовим аргументы для order_by(): выбранное поле + '-id' как запасной ключ.
        # Без него при равных значениях (много объявлений по одной цене) MySQL вправе
        # выдавать их в любом порядке, и на соседних страницах пагинации записи
        # повторялись бы или терялись. id у нас UUIDv7, он растёт со временем, поэтому
        # '-id' даёт стабильный порядок «новые первыми».
        ordering = attrs.get('ordering', DEFAULT_ORDERING)
        field = ORDERING_FIELDS[ordering.lstrip('-')]
        primary = f'-{field}' if ordering.startswith('-') else field
        attrs['order_by'] = (primary, '-id')
        return attrs


class SearchQuerySerializer(serializers.ModelSerializer):
    """Элемент истории поиска пользователя (GET listings/searches/my/)."""

    class Meta:
        model = SearchQuery
        fields = ('id', 'keyword', 'created_at')
        read_only_fields = fields


class PopularSearchSerializer(serializers.Serializer):
    """Элемент «популярных запросов»: слово и сколько раз его искали.

    Это не модель, а результат GROUP BY keyword + COUNT(*), поэтому обычный Serializer.
    """

    keyword = serializers.CharField()
    count = serializers.IntegerField()


class PopularLimitSerializer(serializers.Serializer):
    """Проверка ?limit= для GET listings/searches/popular/ (по умолчанию 10, максимум 100)."""

    limit = serializers.IntegerField(required=False, min_value=1, max_value=100, default=10)
