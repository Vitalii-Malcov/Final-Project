from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from apps.users.models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    """Наследуем стандартный UserAdmin, чтобы пароль в админке хешировался (форма
    создания и отдельная форма смены пароля), а не вводился открытым текстом.
    Переопределяем только поля: у нас нет username, вход по email."""

    ordering = ('email',)
    list_display = ('email', 'first_name', 'last_name', 'roles_display', 'is_staff', 'is_active')
    list_filter = ('is_staff', 'is_active')
    search_fields = ('email', 'first_name', 'last_name', 'phone')

    # Роли — это группы. В списке показываем их одной колонкой, а prefetch_related
    # берёт группы всех пользователей страницы одним запросом (без N+1).
    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related('groups')

    @admin.display(description='Роли')
    def roles_display(self, obj):
        return ', '.join(obj.roles) or '—'

    # Редактирование: группы уже есть в блоке «Права» (поле groups).
    fieldsets = (
        (None, {'fields': ('email', 'password')}),
        ('Личные данные', {'fields': ('first_name', 'last_name', 'phone')}),
        ('Права', {'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        ('Даты', {'fields': ('last_login', 'date_joined')}),
    )
    # Форма «Добавить пользователя»: password1/password2 — это пара «пароль + повтор».
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('email', 'first_name', 'last_name', 'phone', 'groups', 'password1', 'password2'),
        }),
    )
