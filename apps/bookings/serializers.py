from django.utils import timezone
from rest_framework import serializers

from apps.bookings.choices.statuses import BookingStatus
from apps.bookings.models import Booking
from apps.listings.models import Listing
from apps.listings.serializers import OwnerSerializer

MAX_NIGHTS = 365

# Значения ?state= для GET bookings/ -> см. BookingListView.get_queryset.
BOOKING_STATES = ('active', 'completed', 'cancelled', 'rejected')


class BookingListingSerializer(serializers.ModelSerializer):
    """Краткие данные объявления внутри брони (чтобы не гонять вложенный полный объект)."""

    class Meta:
        model = Listing
        fields = ('id', 'title', 'city', 'district', 'address')
        read_only_fields = fields


class BookingSerializer(serializers.ModelSerializer):
    """Чтение брони. nights, cancellation_deadline, is_completed — свойства модели."""

    listing = BookingListingSerializer(read_only=True)
    # Арендодателю нужно знать, кто бронирует: отдаём id и имя, без email и телефона.
    tenant = OwnerSerializer(read_only=True)
    nights = serializers.IntegerField(read_only=True)
    cancellation_deadline = serializers.DateField(read_only=True)
    is_completed = serializers.BooleanField(read_only=True)

    class Meta:
        model = Booking
        fields = (
            'id', 'listing', 'tenant', 'start_date', 'end_date', 'nights',
            'total_price', 'status', 'cancellation_deadline', 'is_completed',
            'created_at', 'updated_at',
        )
        read_only_fields = fields


class BookingCreateSerializer(serializers.ModelSerializer):
    """Создание брони: проверяет только то, что можно проверить без блокировок.

    Проверки «даты свободны» здесь НЕТ намеренно: она зависит от других броней и должна
    выполняться под блокировкой объявления (см. BookingListView.create), иначе между
    проверкой и записью успеет проскочить параллельный запрос.
    """

    # Только активные объявления: на скрытое бронировать нельзя. Несуществующий id и
    # неактивное объявление дают одинаковый ответ 400 — наличие скрытого не раскрываем.
    listing = serializers.PrimaryKeyRelatedField(
        queryset=Listing.objects.filter(is_active=True),
        error_messages={
            'does_not_exist': 'Listing not found or not available for booking.',
            'incorrect_type': 'Listing id must be a valid UUID.',
        },
    )

    class Meta:
        model = Booking
        fields = ('listing', 'start_date', 'end_date')

    def validate(self, attrs):
        start, end = attrs['start_date'], attrs['end_date']
        today = timezone.localdate()  # «сегодня» по Берлину (TIME_ZONE), а не по UTC

        errors = {}
        if start < today:
            errors['start_date'] = 'Start date cannot be in the past.'
        if end <= start:
            # Совпадает с CheckConstraint в БД, но здесь клиент получает понятный 400,
            # а не IntegrityError.
            errors['end_date'] = 'End date must be after start date.'
        elif (end - start).days > MAX_NIGHTS:
            errors['end_date'] = f'Booking cannot be longer than {MAX_NIGHTS} nights.'
        if errors:
            raise serializers.ValidationError(errors)

        if attrs['listing'].owner_id == self.context['request'].user.id:
            raise serializers.ValidationError({'listing': 'You cannot book your own listing.'})
        return attrs

    def create(self, validated_data):
        listing = validated_data['listing']
        nights = (validated_data['end_date'] - validated_data['start_date']).days
        # Цена ФИКСИРУЕТСЯ сейчас: price x ночей. Если арендодатель потом поднимет
        # цену объявления, договорённая сумма брони не изменится.
        validated_data['total_price'] = listing.price * nights
        return super().create(validated_data)


class BookingStateFilterSerializer(serializers.Serializer):
    """Проверка ?state= у GET bookings/."""

    state = serializers.ChoiceField(required=False, choices=BOOKING_STATES)


class BookingStatusFilterSerializer(serializers.Serializer):
    """Проверка ?status= у GET bookings/requests/."""

    status = serializers.ChoiceField(required=False, choices=BookingStatus.choices)
