from django.contrib.auth.models import AbstractBaseUser, Group, PermissionsMixin
from django.db import models
from django.utils import timezone

from apps.core.models import UUIDv7Model
from apps.users.choices.roles import Role
from apps.users.managers import UserManager


class User(UUIDv7Model, AbstractBaseUser, PermissionsMixin):
    """Пользователь системы.

    Роли (арендатор / арендодатель) — это группы Django (поле groups из PermissionsMixin),
    а не отдельное поле: так один человек может быть и арендатором, и арендодателем,
    а права задаются стандартными permissions на группах.

    Наследование:
      * UUIDv7Model      — первичный ключ UUID v7;
      * AbstractBaseUser — password (хеш), last_login, set_password/check_password, но без
                           лишних полей (в отличие от AbstractUser с его username);
      * PermissionsMixin — is_superuser, groups, user_permissions для админки.
    """

    first_name = models.CharField(max_length=150)
    last_name = models.CharField(max_length=150)
    # unique=True создаёт уникальный индекс: он же ускоряет поиск при логине.
    email = models.EmailField(unique=True)
    phone = models.CharField(max_length=32, blank=True)

    is_staff = models.BooleanField(default=False)   # пускать ли в админку
    is_active = models.BooleanField(default=True)   # False = «удалён» без потери истории броней
    date_joined = models.DateTimeField(default=timezone.now)

    objects = UserManager()

    USERNAME_FIELD = 'email'  # по этому полю входим
    # Что спросит createsuperuser кроме email и пароля.
    REQUIRED_FIELDS = ['first_name', 'last_name']

    class Meta:
        db_table = 'users'

    def __str__(self):
        return self.email

    @property
    def roles(self):
        """Имена ролей пользователя, например ['landlord', 'tenant'].

        Берём только группы-роли: администратор может завести и другие группы,
        в API они не нужны. groups.all() использует prefetch_related, если он был
        (так в админке список пользователей не делает запрос на каждую строку).
        """
        return sorted(g.name for g in self.groups.all() if g.name in Role.values)

    def add_roles(self, *names):
        """Добавить роли (идемпотентно: повторное добавление ничего не меняет).

        Группа обязана существовать — её создала миграция. Если группы нет, это ошибка
        настройки, а не ошибка пользователя, поэтому get() упадёт громко, а не молча
        выдаст пользователю роль без прав.
        """
        self.groups.add(*(Group.objects.get(name=name) for name in names))
