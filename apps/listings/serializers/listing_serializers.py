from rest_framework import serializers

from apps.listings.models import Listing
from apps.users.models import User


class OwnerSerializer(serializers.ModelSerializer):
    """Краткие данные арендодателя внутри объявления.

    Email и телефон намеренно не отдаём: объявления читают все, включая анонимов,
    а контакты — персональные данные.
    """

    class Meta:
        model = User
        fields = ('id', 'first_name', 'last_name')
        read_only_fields = fields


class ListingSerializer(serializers.ModelSerializer):
    """Чтение: то, что клиент видит в списке и в карточке объявления.

    views_count / reviews_count / avg_rating — это аннотации из
    Listing.objects.with_stats(), в самой таблице таких колонок нет. Поэтому
    queryset во view обязан быть с .with_stats(), иначе поля пропадут из ответа.
    """

    owner = OwnerSerializer(read_only=True)
    views_count = serializers.IntegerField(read_only=True)
    reviews_count = serializers.IntegerField(read_only=True)
    avg_rating = serializers.FloatField(read_only=True, allow_null=True)  # null, пока нет отзывов

    class Meta:
        model = Listing
        fields = (
            'id', 'owner', 'title', 'description', 'city', 'district', 'address',
            'price', 'rooms', 'housing_type', 'is_active',
            'views_count', 'reviews_count', 'avg_rating',
            'created_at', 'updated_at',
        )
        read_only_fields = fields


class ListingWriteSerializer(serializers.ModelSerializer):
    """Запись: создание (POST) и изменение (PUT/PATCH).

    Отдельный от ListingSerializer класс, потому что набор полей разный: на запись
    нельзя принимать owner, счётчики статистики и даты. Правила (title >= 5 символов,
    description >= 20, price >= 1, rooms 1..50) лежат в валидаторах МОДЕЛИ, а
    ModelSerializer подхватывает их автоматически. Так правило записано один раз и
    работает и в API, и в админке.
    """

    class Meta:
        model = Listing
        fields = (
            'title', 'description', 'city', 'district', 'address',
            'price', 'rooms', 'housing_type', 'is_active',
        )
        # district в модели blank=True, поэтому ModelSerializer сам делает его необязательным.

    # owner здесь не принимаем никогда: его проставит view из токена
    # (serializer.save(owner=request.user)). Иначе арендодатель мог бы создать
    # объявление «от имени» другого пользователя, передав чужой owner в теле.


class ListingToggleStatusSerializer(serializers.Serializer):
    """PATCH listings/<id>/toggle-status/: тело необязательно.

    Без тела — переключить на противоположное. С {"is_active": false} — выставить явно.
    Явное значение полезно, когда запрос повторили (сеть моргнула): повтор «выключить»
    не включит объявление обратно, а повтор «переключить» — включил бы.
    """

    is_active = serializers.BooleanField(required=False)
