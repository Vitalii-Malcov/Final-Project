from django.urls import include, path

# Единая точка сборки API. Префикс api/v1/ добавляет config/urls.py.
# Остальные приложения (listings, bookings, reviews) подключим на следующих этапах.
urlpatterns = [
    path('auth/', include('apps.users.urls')),
]
