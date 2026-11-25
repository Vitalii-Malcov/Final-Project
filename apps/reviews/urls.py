from django.urls import path

from apps.reviews import views

# Подключается в routers.py с префиксом listings/<uuid:listing_id>/reviews/,
# поэтому здесь путь пустой.
urlpatterns = [
    path('', views.ListingReviewListCreateView.as_view(), name='listing-reviews'),
]
