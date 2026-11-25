from django.db import IntegrityError, transaction
from django.http import Http404
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.generics import ListCreateAPIView
from rest_framework.response import Response

from apps.bookings.models import Booking
from apps.core.permissions import IsTenantOrReadOnly
from apps.listings.models import Listing
from apps.reviews.models import Review
from apps.reviews.serializers import ReviewCreateSerializer, ReviewSerializer


class ListingReviewListCreateView(ListCreateAPIView):
    """GET listings/<id>/reviews/ — все отзывы (публично); POST — оставить отзыв (арендатор)."""

    # Явно: чтение открыто всем, включая анонимов (иначе дефолтный IsAuthenticated дал бы 401).
    permission_classes = [IsTenantOrReadOnly]
    serializer_class = ReviewSerializer

    def get_listing(self):
        listing = get_object_or_404(Listing, pk=self.kwargs['listing_id'])
        # Неактивное объявление скрыто от всех, кроме владельца, и его отзывы тоже:
        # иначе «скрытое» объявление можно было бы вычислить по отзывам.
        if not listing.is_active and listing.owner_id != self.request.user.id:
            raise Http404
        return listing

    def get_queryset(self):
        return (
            Review.objects.filter(listing=self.get_listing())
            .select_related('author')
            .order_by('-created_at', '-id')  # новые первыми; '-id' — стабильная пагинация
        )

    def create(self, request, *args, **kwargs):
        listing = self.get_listing()

        serializer = ReviewCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)  # неверная оценка / пустой текст -> 400

        # Отзыв — только после настоящего проживания: подтверждённая бронь этого арендатора
        # на ЭТО объявление, выезд по которой уже наступил (BookingQuerySet.completed()).
        # Pending, отменённая, отклонённая или ещё будущая бронь не считаются.
        booking = (
            Booking.objects.completed()
            .filter(listing=listing, tenant=request.user)
            .order_by('-end_date')
            .first()
        )
        if booking is None:
            return Response(
                {'detail': 'You can review a listing only after a completed stay.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Один отзыв на объявление от одного автора.
        if Review.objects.filter(listing=listing, author=request.user).exists():
            return Response(
                {'detail': 'You have already reviewed this listing.'},
                status=status.HTTP_409_CONFLICT,
            )

        try:
            # atomic нужен, чтобы при IntegrityError транзакция откатилась чисто и
            # соединение с БД осталось рабочим.
            with transaction.atomic():
                review = serializer.save(listing=listing, author=request.user, booking=booking)
        except IntegrityError:
            # Страховка от гонки: два одновременных POST оба прошли exists() выше, но
            # UniqueConstraint(listing, author) в БД пропустит только один.
            return Response(
                {'detail': 'You have already reviewed this listing.'},
                status=status.HTTP_409_CONFLICT,
            )

        review = Review.objects.select_related('author').get(pk=review.pk)
        return Response(ReviewSerializer(review).data, status=status.HTTP_201_CREATED)
