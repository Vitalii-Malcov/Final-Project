from functools import cached_property

from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.generics import (
    GenericAPIView,
    ListAPIView,
    ListCreateAPIView,
    RetrieveUpdateDestroyAPIView,
)
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from apps.bookings.choices.statuses import BookingStatus
from apps.bookings.models import Booking
from apps.core.permissions import IsLandlord, IsLandlordOrReadOnly, IsOwnerOrReadOnly
from apps.listings.models import Listing, ListingView, SearchQuery
from apps.listings.serializers import (
    ListingFilterSerializer,
    ListingSerializer,
    ListingToggleStatusSerializer,
    ListingWriteSerializer,
)


def apply_filters(queryset, params):
    """Применяет проверенные параметры (validated_data ListingFilterSerializer) к queryset."""
    # Поиск по ключевым словам: КАЖДОЕ слово должно встретиться в заголовке ИЛИ описании.
    # «berlin balkon» найдёт объявления, где есть оба слова (не обязательно рядом).
    # icontains экранирует % и _ сам, SQL-инъекции здесь нет.
    for word in params.get('search', '').split():
        queryset = queryset.filter(Q(title__icontains=word) | Q(description__icontains=word))

    if 'price_min' in params:
        queryset = queryset.filter(price__gte=params['price_min'])
    if 'price_max' in params:
        queryset = queryset.filter(price__lte=params['price_max'])
    if params.get('city'):
        queryset = queryset.filter(city__iexact=params['city'])  # «berlin» == «Berlin»
    if params.get('district'):
        queryset = queryset.filter(district__iexact=params['district'])
    if 'rooms_min' in params:
        queryset = queryset.filter(rooms__gte=params['rooms_min'])
    if 'rooms_max' in params:
        queryset = queryset.filter(rooms__lte=params['rooms_max'])
    if params.get('housing_type'):  # список, например ['apartment', 'house']
        queryset = queryset.filter(housing_type__in=params['housing_type'])

    return queryset.order_by(*params['order_by'])


def stats_queryset():
    """Базовый queryset: все объявления со статистикой и владельцем одним запросом.

    select_related('owner') делает JOIN, иначе на каждое объявление в списке ушёл бы
    отдельный запрос за владельцем (проблема N+1).
    """
    return Listing.objects.with_stats().select_related('owner')


class ListingObjectMixin:
    """Поиск одного объявления по <uuid:pk> с правилом видимости.

    Неактивное объявление видит только владелец. Всем остальным отвечаем 404, а не 403:
    «запрещено» подтвердило бы, что такое объявление существует.
    """

    def get_queryset(self):
        return stats_queryset()

    def get_object(self):
        obj = get_object_or_404(self.get_queryset(), pk=self.kwargs['pk'])
        if not obj.is_active and obj.owner_id != self.request.user.id:
            raise Http404
        # Права на объект (IsOwnerOrReadOnly) проверяем ПОСЛЕ скрытия: иначе для
        # неактивного чужого объявления вернулось бы 403 вместо 404.
        self.check_object_permissions(self.request, obj)
        return obj


class ListingListCreateView(ListCreateAPIView):
    """GET — публичный список с поиском и фильтрами; POST — создание (арендодатель)."""

    # Явно: чтение открыто всем, включая анонимов (иначе сработал бы дефолтный
    # IsAuthenticated и GET без токена вернул бы 401), запись — только landlord.
    permission_classes = [IsLandlordOrReadOnly]
    serializer_class = ListingSerializer

    @cached_property
    def filter_params(self):
        # Любой неверный параметр -> ValidationError -> 400.
        # cached_property: проверяем один раз за запрос, хотя читаем в нескольких местах.
        serializer = ListingFilterSerializer(data=self.request.query_params)
        serializer.is_valid(raise_exception=True)
        return serializer.validated_data

    def get_queryset(self):
        return apply_filters(stats_queryset().active(), self.filter_params)

    def list(self, request, *args, **kwargs):
        response = super().list(request, *args, **kwargs)
        self._save_search_history(request)  # только если выше не было ошибки (400/404)
        return response

    def _save_search_history(self, request):
        # Нормализуем: нижний регистр и один пробел между словами, чтобы
        # «Berlin  Balkon» и «berlin balkon» считались одним запросом.
        keyword = ' '.join(self.filter_params.get('search', '').lower().split())
        if not keyword:
            return
        # Листание результатов того же поиска (?page=2...) — не новый поиск.
        if request.query_params.get('page') not in (None, '', '1'):
            return
        SearchQuery.objects.create(
            keyword=keyword,
            user=request.user if request.user.is_authenticated else None,
        )

    def create(self, request, *args, **kwargs):
        serializer = ListingWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        # Владелец — из токена. Тело запроса на это поле влиять не может.
        listing = serializer.save(owner=request.user)
        # Отвечаем объектом со статистикой (у только что созданного её ещё нет).
        data = ListingSerializer(stats_queryset().get(pk=listing.pk)).data
        return Response(data, status=status.HTTP_201_CREATED)


class ListingDetailView(ListingObjectMixin, RetrieveUpdateDestroyAPIView):
    """GET — карточка (публично); PUT/PATCH/DELETE — только владелец."""

    permission_classes = [IsOwnerOrReadOnly]
    serializer_class = ListingSerializer

    def retrieve(self, request, *args, **kwargs):
        listing = self.get_object()
        # Просмотр владельцем собственного объявления не считаем: иначе арендодатель
        # накручивал бы себе популярность простым обновлением страницы.
        if listing.owner_id != request.user.id:
            ListingView.objects.create(
                listing=listing,
                user=request.user if request.user.is_authenticated else None,
            )
            listing.views_count += 1  # объект уже загружен до записи; подправляем счётчик в ответе
        return Response(ListingSerializer(listing).data)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)  # PATCH -> partial=True, PUT -> False
        listing = self.get_object()
        serializer = ListingWriteSerializer(listing, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(ListingSerializer(stats_queryset().get(pk=listing.pk)).data)

    def destroy(self, request, *args, **kwargs):
        listing = self.get_object()
        # Нельзя удалить объявление, пока по нему есть подтверждённая бронь, которая
        # ещё не закончилась (идущая сейчас или будущая): у арендатора есть
        # подтверждённые планы. Конфликт состояния -> 409.
        has_active_booking = Booking.objects.filter(
            listing=listing,
            status=BookingStatus.CONFIRMED,
            end_date__gt=timezone.localdate(),
        ).exists()
        if has_active_booking:
            return Response(
                {'detail': 'Cannot delete a listing with confirmed upcoming bookings.'},
                status=status.HTTP_409_CONFLICT,
            )
        listing.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class ListingToggleStatusView(ListingObjectMixin, GenericAPIView):
    """PATCH listings/<id>/toggle-status/ — скрыть или снова показать объявление."""

    permission_classes = [IsOwnerOrReadOnly]
    serializer_class = ListingToggleStatusSerializer

    def patch(self, request, pk):
        listing = self.get_object()
        serializer = ListingToggleStatusSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        # Явное значение из тела, а если тела нет — противоположное текущему.
        listing.is_active = serializer.validated_data.get('is_active', not listing.is_active)
        # update_fields ускоряет UPDATE, но auto_now срабатывает только для полей из
        # этого списка: без 'updated_at' дата изменения бы не обновилась.
        listing.save(update_fields=['is_active', 'updated_at'])
        return Response(ListingSerializer(listing).data)


class MyListingsView(ListAPIView):
    """GET listings/my/ — свои объявления арендодателя, включая неактивные."""

    permission_classes = [IsLandlord]
    serializer_class = ListingSerializer

    def get_queryset(self):
        serializer = ListingFilterSerializer(data=self.request.query_params)
        serializer.is_valid(raise_exception=True)
        queryset = stats_queryset().filter(owner=self.request.user)  # без .active()
        return apply_filters(queryset, serializer.validated_data)


class PopularListingsView(ListAPIView):
    """GET listings/popular/ — активные объявления, самые просматриваемые первыми."""

    permission_classes = [AllowAny]  # публично
    serializer_class = ListingSerializer

    def get_queryset(self):
        # '-id' — запасной ключ для стабильной пагинации при равном числе просмотров.
        return stats_queryset().active().order_by('-views_count', '-id')
