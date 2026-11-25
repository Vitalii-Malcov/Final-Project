from django.http import JsonResponse
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.authentication import JWTAuthentication

API_PREFIX = '/api/v1/'

# Публичные пути: без токена иначе никто не смог бы зарегистрироваться и войти.
PUBLIC_PATHS = {
    'auth/register/',
    'auth/login/',
    'auth/refresh/',
}

# Приватные пути, закрытые даже для чтения (GET): это данные конкретного человека.
PRIVATE_EXACT_PATHS = {
    'auth/me/',
    'auth/logout/',
    'listings/my/',
    'listings/searches/my/',
}
PRIVATE_PREFIXES = ('bookings/',)  # bookings/, bookings/<id>/, bookings/requests/ ...

# Методы, которые ничего не меняют. Всё остальное (POST/PUT/PATCH/DELETE) меняет данные.
SAFE_METHODS = {'GET', 'HEAD', 'OPTIONS'}


class JWTProtectedRoutesMiddleware:
    """Уровень 1 защиты: «есть ли вообще валидный токен».

    Работает ДО того, как запрос дойдёт до view, и отсекает анонимов у приватных
    маршрутов и у любого изменяющего запроса. Кто именно может выполнить действие
    (арендатор / арендодатель / владелец) решает уровень 2 — permission_classes в DRF.
    Такое разделение — «вход в здание» (middleware) и «ключ от конкретной комнаты»
    (permissions).
    """

    def __init__(self, get_response):
        # Django создаёт middleware один раз при старте и передаёт следующий
        # обработчик в цепочке.
        self.get_response = get_response
        self.jwt_auth = JWTAuthentication()

    def __call__(self, request):
        if self._requires_token(request):
            try:
                # Вернёт None, если заголовка Authorization нет; бросит исключение,
                # если токен просрочен, подделан, это refresh вместо access
                # или пользователь удалён/деактивирован.
                result = self.jwt_auth.authenticate(request)
            except AuthenticationFailed:  # InvalidToken — его подкласс
                return self._unauthorized('Token is invalid or expired.')

            if result is None:
                return self._unauthorized('Authentication credentials were not provided.')

        return self.get_response(request)

    @staticmethod
    def _requires_token(request):
        """Нужен ли для этого запроса токен."""
        # Админка и всё, что не под /api/v1/, — не наша зона: у админки своя сессионная защита.
        if not request.path.startswith(API_PREFIX):
            return False

        relative = request.path[len(API_PREFIX):]

        if relative in PUBLIC_PATHS:
            return False

        if relative in PRIVATE_EXACT_PATHS or relative.startswith(PRIVATE_PREFIXES):
            return True

        # Любое изменение данных требует токен. Заодно это страховка: если
        # забудем закрыть новый POST-маршрут, он всё равно не будет анонимным.
        return request.method not in SAFE_METHODS

    @staticmethod
    def _unauthorized(message):
        response = JsonResponse({'detail': message}, status=401)
        response['WWW-Authenticate'] = 'Bearer'  # по стандарту HTTP 401 сообщает схему авторизации
        return response
