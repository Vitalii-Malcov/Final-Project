from django.apps import apps as global_apps
from django.contrib.auth.management import create_permissions
from django.db import migrations

# Роль -> какие стандартные model permissions она даёт ('приложение.действие_модель').
# Значения скопированы в миграцию намеренно: миграция должна навсегда оставаться
# такой, какой её применили, даже если проект потом изменит свои константы.
ROLE_PERMISSIONS = {
    'landlord': [
        'listings.add_listing',
        'listings.change_listing',
        'listings.delete_listing',
        'bookings.change_booking',  # подтвердить / отклонить заявку
    ],
    'tenant': [
        'bookings.add_booking',
        'reviews.add_review',
    ],
}


def ensure_permissions(apps):
    """Создаёт model permissions для наших приложений ПРЯМО СЕЙЧАС.

    Почему так. Обычно permissions создаёт сигнал post_migrate, но он срабатывает
    ПОСЛЕ всех миграций. На чистой базе (Docker, тесты) в момент нашей миграции таблица
    auth_permission для listings/bookings/reviews ещё пуста, и выдавать группам было бы нечего.

    Почему не post_migrate-обработчик вместо миграции: тогда группы появлялись бы
    не при migrate-шаге, а «потом», и следующая миграция (перенос старых ролей в группы)
    не нашла бы их. Миграция делает всё по порядку и детерминированно.
    Повторного создания не будет: create_permissions пропускает уже существующие права,
    поэтому штатный post_migrate после нас ничего не продублирует.
    """
    for app_label in ('listings', 'bookings', 'reviews'):
        app_config = global_apps.get_app_config(app_label)
        # В миграции у реального app_config может быть models_module=None (его
        # выставляет загрузка models.py при штатном запуске); create_permissions без
        # него сразу выходит. Временно ставим флаг и возвращаем обратно.
        previous = app_config.models_module
        app_config.models_module = previous or True
        try:
            create_permissions(app_config, apps=apps, verbosity=0)
        finally:
            app_config.models_module = previous


def create_groups(apps, schema_editor):
    ensure_permissions(apps)
    Group = apps.get_model('auth', 'Group')
    Permission = apps.get_model('auth', 'Permission')

    for name, perms in ROLE_PERMISSIONS.items():
        group, _ = Group.objects.get_or_create(name=name)
        for dotted in perms:
            app_label, codename = dotted.split('.')
            group.permissions.add(
                Permission.objects.get(content_type__app_label=app_label, codename=codename)
            )


def delete_groups(apps, schema_editor):
    apps.get_model('auth', 'Group').objects.filter(name__in=ROLE_PERMISSIONS).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('auth', '0012_alter_user_first_name_max_length'),
        ('contenttypes', '0002_remove_content_type_name'),
        ('users', '0001_initial'),
        # Модели, чьи права мы выдаём, должны уже существовать в состоянии миграций.
        ('listings', '0002_initial'),
        ('bookings', '0003_initial'),
        ('reviews', '0002_initial'),
    ]

    operations = [migrations.RunPython(create_groups, delete_groups)]
