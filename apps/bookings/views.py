from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import APIException
from rest_framework.generics import GenericAPIView, ListAPIView, ListCreateAPIView, RetrieveAPIView
from rest_framework.response import Response

from apps.bookings.choices.statuses import BookingStatus
from apps.bookings.models import Booking
from apps.bookings.serializers import (
    BookingCreateSerializer,
    BookingSerializer,
    BookingStateFilterSerializer,
    BookingStatusFilterSerializer,
)
from apps.core.permissions import IsLandlord, IsTenant
from apps.listings.models import Listing


class BookingConflict(APIException):
    """409 Conflict: запрос корректен, но противоречит ТЕКУЩЕМУ состоянию данных.

    Отличие от 400: при 400 клиент прислал неверные данные (даты в прошлом). При 409
    данные верные, но сейчас действие невозможно (даты заняты, бронь уже
    подтверждена, срок отмены прошёл). Позже, в другом состоянии, тот же запрос
    мог бы пройти.

    Исключение, брошенное внутри `with transaction.atomic()`, ОТКАТЫВАЕТ транзакцию
    целиком, так что частично применённых изменений не останется.
    """

    status_code = status.HTTP_409_CONFLICT
    default_detail = 'Conflict with the current state of the booking.'
    default_code = 'conflict'


def booking_queryset():
    """Бронь + объявление + арендатор одним запросом (иначе N+1 в списках)."""
    return Booking.objects.select_related('listing', 'tenant')


def lock_listing(listing_id):
    """Берёт блокировку на строку объявления до конца текущей транзакции.

    SELECT ... FOR UPDATE: пока транзакция не завершилась, любая другая транзакция,
    которая тоже пытается заблокировать эту же строку, ЖДЁТ. Это превращает
    «проверить пересечения -> записать» из двух шагов, между которыми может вклиниться
    параллельный запрос, в один неделимый шаг.

    Блокируем именно объявление, а не брони: пересечения ищутся среди всех броней
    объявления, включая ещё не существующие. Заблокировать то, чего нет, нельзя,
    а строка объявления есть всегда и служит «замком» для всех его броней.
    Работает ТОЛЬКО внутри transaction.atomic(): вне транзакции блокировка
    снимается сразу после запроса, и смысла в ней нет.
    """
    return Listing.objects.select_for_update().get(pk=listing_id)


# ---------------------------------------------------------------- арендатор

class BookingListCreateView(ListCreateAPIView):
    """GET bookings/ — мои брони (?state=); POST bookings/ — создать бронь. Только арендатор."""

    permission_classes = [IsTenant]
    serializer_class = BookingSerializer

    def get_queryset(self):
        params = BookingStateFilterSerializer(data=self.request.query_params)
        params.is_valid(raise_exception=True)
        state = params.validated_data.get('state')

        # Свои брони: чужие здесь не видны вообще.
        queryset = booking_queryset().filter(tenant=self.request.user)
        if state == 'active':
            queryset = queryset.active()        # pending/confirmed и ещё не закончились
        elif state == 'completed':
            queryset = queryset.completed()     # confirmed и выезд уже наступил
        elif state == 'cancelled':
            queryset = queryset.filter(status=BookingStatus.CANCELLED)
        elif state == 'rejected':
            queryset = queryset.filter(status=BookingStatus.REJECTED)
        # '-id' — запасной ключ для стабильной пагинации при равном created_at.
        return queryset.order_by('-created_at', '-id')

    def create(self, request, *args, **kwargs):
        serializer = BookingCreateSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)  # неверные данные -> 400
        listing = serializer.validated_data['listing']
        start = serializer.validated_data['start_date']
        end = serializer.validated_data['end_date']

        with transaction.atomic():
            # Замок на объявление: создание и подтверждение броней этого объявления
            # выстраиваются в очередь, а не выполняются одновременно.
            lock_listing(listing.pk)

            # 1) Пересечение с ПОДТВЕРЖДЁННОЙ бронью любого арендатора: эти даты заняты.
            #    (pending чужих не мешает: это лишь заявки, выберет арендодатель.)
            if Booking.objects.filter(listing=listing, status=BookingStatus.CONFIRMED) \
                    .overlapping(start, end).exists():
                raise BookingConflict('The listing is already booked for these dates.')

            # 2) Пересечение с СОБСТВЕННОЙ заявкой того же арендатора: две заявки на одни
            #    и те же даты от одного человека — это ошибка или двойной клик.
            if Booking.objects.filter(listing=listing, tenant=request.user, status=BookingStatus.PENDING) \
                    .overlapping(start, end).exists():
                raise BookingConflict('You already have a pending request for overlapping dates.')

            booking = serializer.save(tenant=request.user)  # total_price считается в create()

        return Response(BookingSerializer(booking_queryset().get(pk=booking.pk)).data,
                        status=status.HTTP_201_CREATED)


class BookingCancelView(GenericAPIView):
    """PATCH bookings/<id>/cancel/ — арендатор отменяет свою бронь."""

    permission_classes = [IsTenant]
    serializer_class = BookingSerializer

    def patch(self, request, pk):
        # Только СВОЯ бронь: по чужой id ответ 404, существование не раскрываем.
        get_object_or_404(Booking, pk=pk, tenant=request.user)

        with transaction.atomic():
            # Блокируем строку брони и перечитываем её: пока мы проверяли, владелец мог
            # успеть подтвердить/отклонить бронь, и статус из первого чтения устарел.
            booking = Booking.objects.select_for_update().get(pk=pk)

            if booking.status not in (BookingStatus.PENDING, BookingStatus.CONFIRMED):
                raise BookingConflict(f'A booking with status "{booking.status}" cannot be cancelled.')

            # Отменять можно не позже, чем за N дней до заезда (N из .env, по умолчанию 1).
            # Свойство cancellation_deadline = start_date - N дней. Сравниваем с «сегодня»
            # по Берлину: в сам день дедлайна отмена ещё разрешена, на следующий уже нет.
            if timezone.localdate() > booking.cancellation_deadline:
                raise BookingConflict(
                    f'Cancellation deadline has passed (last day to cancel: {booking.cancellation_deadline}).'
                )

            booking.status = BookingStatus.CANCELLED
            booking.save(update_fields=['status', 'updated_at'])  # без updated_at дата изменения не обновится

        return Response(BookingSerializer(booking_queryset().get(pk=pk)).data)


# ------------------------------------------------------ арендатор и владелец

class BookingDetailView(RetrieveAPIView):
    """GET bookings/<id>/ — бронь видят только арендатор и владелец объявления."""

    serializer_class = BookingSerializer  # права: дефолтный IsAuthenticated + фильтр queryset

    def get_queryset(self):
        user = self.request.user
        # Бронь видит её арендатор ИЛИ владелец жилья. Остальные получают 404: фильтр
        # в queryset одновременно и проверка прав, и скрывает чужие брони.
        return booking_queryset().filter(Q(tenant=user) | Q(listing__owner=user))


# ----------------------------------------------------------------- владелец

class BookingRequestsView(ListAPIView):
    """GET bookings/requests/ — заявки на мои объявления (?status=). Только арендодатель."""

    permission_classes = [IsLandlord]
    serializer_class = BookingSerializer

    def get_queryset(self):
        params = BookingStatusFilterSerializer(data=self.request.query_params)
        params.is_valid(raise_exception=True)

        queryset = booking_queryset().filter(listing__owner=self.request.user)
        if 'status' in params.validated_data:
            queryset = queryset.filter(status=params.validated_data['status'])
        return queryset.order_by('-created_at', '-id')


class BookingConfirmView(GenericAPIView):
    """PATCH bookings/<id>/confirm/ — владелец подтверждает заявку.

    Самое чувствительное место проекта: после подтверждения даты считаются занятыми.
    """

    permission_classes = [IsLandlord]
    serializer_class = BookingSerializer

    def patch(self, request, pk):
        # Только заявки на СВОИ объявления; чужие -> 404.
        booking = get_object_or_404(Booking, pk=pk, listing__owner=request.user)

        with transaction.atomic():
            # ШАГ 1. Замок на объявление. Два параллельных confirm по одному объявлению
            # теперь идут строго друг за другом. Без замка оба прочли бы «подтверждённых
            # пересечений нет», оба записали бы confirmed, и жильё оказалось бы
            # забронировано дважды. Порядок блокировок всегда «объявление -> бронь»,
            # так транзакции не могут заблокировать друг друга навечно (deadlock).
            lock_listing(booking.listing_id)

            # ШАГ 2. Перечитываем бронь УЖЕ под замком: пока мы ждали, соседний confirm
            # мог отклонить именно эту заявку, и статус из первого чтения устарел.
            booking = Booking.objects.select_for_update().get(pk=pk)

            if booking.status != BookingStatus.PENDING:
                raise BookingConflict(f'Only pending bookings can be confirmed (current status: "{booking.status}").')
            if booking.start_date < timezone.localdate():
                raise BookingConflict('Cannot confirm a booking whose start date is in the past.')

            # ШАГ 3. Конфликт с уже подтверждённой бронью -> 409.
            # exclude(pk=...) — чтобы бронь не конфликтовала сама с собой.
            if Booking.objects.filter(listing_id=booking.listing_id, status=BookingStatus.CONFIRMED) \
                    .overlapping(booking.start_date, booking.end_date) \
                    .exclude(pk=booking.pk).exists():
                raise BookingConflict('These dates are already taken by another confirmed booking.')

            # ШАГ 4. Подтверждаем.
            booking.status = BookingStatus.CONFIRMED
            booking.save(update_fields=['status', 'updated_at'])

            # ШАГ 5. Все остальные pending с пересекающимися датами отклоняем автоматически:
            # они больше не могут быть подтверждены, и арендаторам незачем ждать вечно.
            # update() — один UPDATE для всех строк сразу. Он НЕ вызывает save(), поэтому
            # auto_now не срабатывает, и updated_at выставляем вручную.
            Booking.objects.filter(listing_id=booking.listing_id, status=BookingStatus.PENDING) \
                .overlapping(booking.start_date, booking.end_date) \
                .exclude(pk=booking.pk) \
                .update(status=BookingStatus.REJECTED, updated_at=timezone.now())

        return Response(BookingSerializer(booking_queryset().get(pk=pk)).data)


class BookingRejectView(GenericAPIView):
    """PATCH bookings/<id>/reject/ — владелец отклоняет заявку."""

    permission_classes = [IsLandlord]
    serializer_class = BookingSerializer

    def patch(self, request, pk):
        get_object_or_404(Booking, pk=pk, listing__owner=request.user)

        with transaction.atomic():
            # Блокируем бронь и перечитываем: параллельный confirm мог её уже изменить.
            # Замок на объявление не нужен: отклонение освобождает даты и ничего не занимает.
            booking = Booking.objects.select_for_update().get(pk=pk)

            if booking.status != BookingStatus.PENDING:
                raise BookingConflict(f'Only pending bookings can be rejected (current status: "{booking.status}").')

            booking.status = BookingStatus.REJECTED
            booking.save(update_fields=['status', 'updated_at'])

        return Response(BookingSerializer(booking_queryset().get(pk=pk)).data)
