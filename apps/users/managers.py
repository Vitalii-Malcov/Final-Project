from django.contrib.auth.base_user import BaseUserManager


class UserManager(BaseUserManager):
    """Менеджер нужен, потому что стандартный create_user ждёт username, а у нас вход по email."""

    use_in_migrations = True

    def _create_user(self, email, password, **extra_fields):
        if not email:
            raise ValueError('Email обязателен.')
        # Приводим весь email к нижнему регистру: иначе Bob@x.com и bob@x.com
        # были бы двумя разными аккаунтами. (normalize_email понижает только домен.)
        email = self.normalize_email(email).lower()
        user = self.model(email=email, **extra_fields)
        # set_password сохраняет хеш (PBKDF2), а не сам пароль. Писать password=... в
        # модель напрямую нельзя: пароль лёг бы в БД открытым текстом.
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', False)
        extra_fields.setdefault('is_superuser', False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)       # доступ в админку
        extra_fields.setdefault('is_superuser', True)   # все права без явной выдачи
        if not extra_fields['is_staff'] or not extra_fields['is_superuser']:
            raise ValueError('У суперпользователя is_staff и is_superuser должны быть True.')
        return self._create_user(email, password, **extra_fields)
