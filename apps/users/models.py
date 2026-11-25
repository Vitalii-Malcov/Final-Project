from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.db import models
from django.utils import timezone

from apps.core.models import UUIDv7Model
from apps.users.choices.roles import Role
from apps.users.managers import UserManager


class User(UUIDv7Model, AbstractBaseUser, PermissionsMixin):
    """Пользователь системы: арендатор или арендодатель.

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
    role = models.CharField(max_length=16, choices=Role.choices, default=Role.TENANT)

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
    def is_landlord(self):
        return self.role == Role.LANDLORD

    @property
    def is_tenant(self):
        return self.role == Role.TENANT
