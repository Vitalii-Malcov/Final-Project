from rest_framework.permissions import SAFE_METHODS, BasePermission

# Уровень 2 защиты. Middleware уже убедился, что токен валиден; здесь решаем,
# МОЖЕТ ЛИ этот пользователь выполнить действие.
#
# Роли — это группы Django, а права — стандартные model permissions на группах
# (выдаёт миграция users/0002). Проверяем КОНКРЕТНОЕ ПРАВО через user.has_perm(),
# а не имя группы и не поле: так администратор может забрать у группы право в админке,
# и это подействует сразу. Пользователь берётся из БД по токену, а не из claim 'roles'
# в самом токене: иначе изменение групп начало бы действовать только через 30 минут,
# пока живёт старый access-токен.
#
# has_perm: для суперпользователя всегда True, для неактивного всегда False.

LISTING_WRITE_PERMS = {
    'POST': 'listings.add_listing',
    'PUT': 'listings.change_listing',
    'PATCH': 'listings.change_listing',
    'DELETE': 'listings.delete_listing',
}


class HasPerm(BasePermission):
    """Основа: нужно право, зависящее от HTTP-метода.

    perms        — словарь «метод -> код права»; ключ '*' подходит для любого метода.
    open_to_read — True: безопасные методы (GET/HEAD/OPTIONS) разрешены всем, включая анонимов.
    Метод без права в словаре запрещён (безопаснее, чем разрешён по забывчивости).
    """

    perms = {}
    open_to_read = False
    message = 'You do not have permission to perform this action.'

    def has_permission(self, request, view):
        if self.open_to_read and request.method in SAFE_METHODS:
            return True
        user = request.user
        if not (user and user.is_authenticated):
            return False
        perm = self.perms.get(request.method, self.perms.get('*'))
        return perm is not None and user.has_perm(perm)


class IsLandlord(HasPerm):
    """Арендодатель: может публиковать объявления (listings.add_listing)."""

    perms = {'*': 'listings.add_listing'}
    message = 'You need the permission to manage listings (landlord role).'


class IsTenant(HasPerm):
    """Арендатор: может бронировать (bookings.add_booking)."""

    perms = {'*': 'bookings.add_booking'}
    message = 'You need the permission to make bookings (tenant role).'


class CanManageBookings(HasPerm):
    """Подтверждение/отклонение заявок и список заявок: bookings.change_booking."""

    perms = {'*': 'bookings.change_booking'}
    message = 'You need the permission to manage booking requests (landlord role).'


class IsTenantOrReadOnly(HasPerm):
    """Читать может любой, отзыв оставить — только с reviews.add_review."""

    perms = {'POST': 'reviews.add_review'}
    open_to_read = True
    message = 'You need the permission to write reviews (tenant role).'


class IsLandlordOrReadOnly(HasPerm):
    """Читать может любой, создавать объявление — только с listings.add_listing."""

    perms = LISTING_WRITE_PERMS
    open_to_read = True
    message = 'You need the permission to manage listings (landlord role).'


class IsOwnerOrReadOnly(HasPerm):
    """Читать может любой; изменять/удалять — нужно право на действие И владение объектом.

    Две независимые проверки: has_permission — «есть ли у пользователя право на такое
    действие вообще» (change_listing / delete_listing), has_object_permission — «это
    ЕГО объект». Одного права мало: иначе любой арендодатель правил бы чужие объявления.

    has_object_permission вызывается DRF только при get_object() — то есть когда
    объект уже найден. Сравниваем по owner_id, а не obj.owner: так не нужен
    лишний SQL-запрос за владельцем.
    """

    perms = LISTING_WRITE_PERMS
    open_to_read = True
    message = 'You need the permission to manage listings (landlord role).'

    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS:
            return True
        if obj.owner_id != request.user.id:
            # Экземпляр класса создаётся на каждый запрос, поэтому менять message безопасно:
            # ответ честно говорит, какая из двух проверок не прошла.
            self.message = 'Only the owner can modify this object.'
            return False
        return True
