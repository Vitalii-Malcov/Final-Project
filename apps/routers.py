from django.urls import include, path

# Единая точка сборки API. Префикс api/v1/ добавляет config/urls.py.
# Приложение reviews подключим на следующем этапе.
urlpatterns = [
    path('auth/', include('apps.users.urls')),
    path('listings/', include('apps.listings.urls')),
    path('bookings/', include('apps.bookings.urls')),
]
