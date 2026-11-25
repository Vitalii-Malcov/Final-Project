from django.db import migrations


def role_to_group(apps, schema_editor):
    """Старое поле role -> членство в группе с тем же именем."""
    User = apps.get_model('users', 'User')
    Group = apps.get_model('auth', 'Group')
    for role in ('tenant', 'landlord'):
        group = Group.objects.get(name=role)
        # Через промежуточную таблицу одним INSERT-ом, а не по пользователю.
        group.user_set.add(*User.objects.filter(role=role))


def group_to_role(apps, schema_editor):
    """Откат: у кого есть группа landlord — role='landlord', у остальных 'tenant'.
    Если было обе роли, старая схема умеет хранить только одну: выигрывает landlord."""
    User = apps.get_model('users', 'User')
    Group = apps.get_model('auth', 'Group')
    # list(): MySQL не разрешает UPDATE таблицы с подзапросом к ней же (ошибка 1093),
    # поэтому id арендодателей читаем заранее, отдельным запросом.
    landlords = list(Group.objects.get(name='landlord').user_set.values_list('pk', flat=True))
    User.objects.filter(pk__in=landlords).update(role='landlord')
    User.objects.exclude(pk__in=landlords).update(role='tenant')


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0002_create_role_groups'),
    ]

    operations = [migrations.RunPython(role_to_group, group_to_role)]
