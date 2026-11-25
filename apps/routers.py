from django.urls import include, path

# Единая точка сборки API. Префикс api/v1/ добавляет config/urls.py.
urlpatterns = [
    path('auth/', include('apps.users.urls')),
    # Отзывы вложены в объявление; идут РАНЬШЕ общего listings/, чтобы было видно:
    # listings/<id>/reviews/ обрабатывает приложение reviews, а не listings.
    path('listings/<uuid:listing_id>/reviews/', include('apps.reviews.urls')),
    path('listings/', include('apps.listings.urls')),
    path('bookings/', include('apps.bookings.urls')),
]
