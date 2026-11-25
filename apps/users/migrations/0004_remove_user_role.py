from django.db import migrations


class Migration(migrations.Migration):
    """Удаляем поле role отдельной миграцией: данные уже перенесены в группы (0003).
    Если что-то пойдёт не так, поле ещё можно вернуть откатом именно этого шага."""

    dependencies = [
        ('users', '0003_roles_to_groups'),
    ]

    operations = [migrations.RemoveField(model_name='user', name='role')]
