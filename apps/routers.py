from django.urls import include, path

# Единая точка сборки API. Префикс api/v1/ добавляет config/urls.py.
# Приложения bookings и reviews подключим на следующих этапах.
urlpatterns = [
    path('auth/', include('apps.users.urls')),
    path('listings/', include('apps.listings.urls')),
]
