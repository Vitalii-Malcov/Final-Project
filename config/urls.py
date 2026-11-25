from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path('admin/', admin.site.urls),
    # Версия в URL (v1): когда API изменится несовместимо, появится v2, а старые клиенты не сломаются.
    path('api/v1/', include('apps.routers')),
]

# Эти имена Django ищет в корневом urls.py. Работают только при DEBUG=False
# (при DEBUG=True Django показывает свою подробную страницу ошибки).
handler404 = 'apps.core.views.not_found'
handler500 = 'apps.core.views.server_error'
