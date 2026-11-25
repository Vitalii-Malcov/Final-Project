from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from apps.users.models import User


class UserSerializer(serializers.ModelSerializer):
    """Публичное представление пользователя. Пароля здесь нет принципиально."""

    class Meta:
        model = User
        fields = ('id', 'first_name', 'last_name', 'email', 'phone', 'role', 'date_joined')
        read_only_fields = fields  # этим сериализатором только отдаём данные


class RegisterSerializer(serializers.ModelSerializer):
    # write_only: пароль принимаем, но никогда не возвращаем в ответе.
    password = serializers.CharField(write_only=True, style={'input_type': 'password'})
    re_password = serializers.CharField(write_only=True, style={'input_type': 'password'})

    class Meta:
        model = User
        fields = ('id', 'first_name', 'last_name', 'email', 'phone', 'role',
                  'password', 're_password')
        read_only_fields = ('id',)
        extra_kwargs = {
            'first_name': {'required': True, 'allow_blank': False},
            'last_name': {'required': True, 'allow_blank': False},
            'role': {'required': True},  # явно выбираем роль, молчаливого дефолта нет
            # Стандартный UniqueValidator чувствителен к регистру и сработал бы
            # до нашего lower(); уникальность проверяем сами в validate_email.
            'email': {'validators': []},
        }

    def validate_email(self, value):
        value = value.lower()  # Bob@x.com и bob@x.com — один и тот же аккаунт
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError('A user with this email already exists.')
        return value

    def validate(self, attrs):
        if attrs['password'] != attrs['re_password']:
            raise serializers.ValidationError({'re_password': 'Passwords do not match.'})

        # Проверяем пароль валидаторами из settings (длина, "не слишком простой",
        # не только цифры, не похож на email/имя). Объект User передаём, чтобы
        # сработала проверка «пароль похож на личные данные».
        candidate = User(
            email=attrs.get('email'),
            first_name=attrs.get('first_name', ''),
            last_name=attrs.get('last_name', ''),
        )
        try:
            validate_password(attrs['password'], user=candidate)
        except DjangoValidationError as exc:  # переводим в формат ошибок DRF -> 400
            raise serializers.ValidationError({'password': list(exc.messages)})
        return attrs

    def create(self, validated_data):
        validated_data.pop('re_password')
        # create_user, а не User.objects.create: только он хеширует пароль через set_password.
        return User.objects.create_user(**validated_data)


class LoginSerializer(TokenObtainPairSerializer):
    """Вход по email + пароль. Возвращает access, refresh и данные пользователя."""

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        # Роль в payload токена: фронтенд может сразу показать нужный интерфейс.
        # Права при этом проверяются по БД (см. core/permissions.py), не по этому полю.
        token['role'] = user.role
        return token

    def validate(self, attrs):
        # Email в базе в нижнем регистре; приводим и вход к нему.
        attrs[self.username_field] = attrs[self.username_field].lower()
        data = super().validate(attrs)  # проверка пароля + генерация access/refresh
        data['user'] = UserSerializer(self.user).data
        return data


class LogoutSerializer(serializers.Serializer):
    refresh = serializers.CharField()
