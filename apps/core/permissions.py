from rest_framework.permissions import SAFE_METHODS, BasePermission

from apps.users.choices.roles import Role

# Уровень 2 защиты. Middleware уже убедился, что токен валиден; здесь решаем,
# МОЖЕТ ЛИ этот пользователь выполнить действие.
#
# Роль берём из объекта request.user (он загружен из БД по токену), а не из
# claim 'role' в самом токене: если админ сменит роль, это подействует сразу,
# а не через 30 минут, пока живёт старый access-токен.


class IsLandlord(BasePermission):
    """Только арендодатель (например, создание объявления)."""

    message = 'Only landlords can perform this action.'

    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and user.role == Role.LANDLORD)


class IsTenant(BasePermission):
    """Только арендатор (бронирование, отзывы)."""

    message = 'Only tenants can perform this action.'

    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and user.role == Role.TENANT)


class IsTenantOrReadOnly(BasePermission):
    """Читать может любой, писать — только арендатор (например, отзывы)."""

    message = 'Only tenants can perform this action.'

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return True
        user = request.user
        return bool(user and user.is_authenticated and user.role == Role.TENANT)


class IsLandlordOrReadOnly(BasePermission):
    """Читать может любой, изменять — только арендодатель."""

    message = 'Only landlords can perform this action.'

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return True
        user = request.user
        return bool(user and user.is_authenticated and user.role == Role.LANDLORD)


class IsOwnerOrReadOnly(BasePermission):
    """Читать может любой, изменять/удалять — только владелец объекта.

    has_object_permission вызывается DRF только при get_object() — то есть когда
    объект уже найден. Сравниваем по owner_id, а не obj.owner: так не нужен
    лишний SQL-запрос за владельцем.
    """

    message = 'Only the owner can modify this object.'

    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS:
            return True
        return obj.owner_id == request.user.id
