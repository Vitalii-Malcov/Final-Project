from rest_framework import status
from rest_framework.generics import CreateAPIView, RetrieveAPIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from apps.users.serializers import (
    LoginSerializer,
    LogoutSerializer,
    RegisterSerializer,
    UserSerializer,
)

# ВАЖНО про AllowAny. В settings по умолчанию стоит IsAuthenticated. Middleware
# пропускает register/login/refresh без токена, но DRF — это второй, независимый
# уровень: без явного AllowAny он вернул бы 401 и здесь. Поэтому на публичных
# view permission_classes указан явно.


class RegisterView(CreateAPIView):
    serializer_class = RegisterSerializer
    permission_classes = [AllowAny]
    authentication_classes = []  # токен не нужен; битый токен в заголовке не должен мешать регистрации


class LoginView(TokenObtainPairView):
    serializer_class = LoginSerializer
    permission_classes = [AllowAny]
    authentication_classes = []


class RefreshView(TokenRefreshView):
    permission_classes = [AllowAny]
    authentication_classes = []


class LogoutView(APIView):
    """Выход = занести refresh-токен в чёрный список.

    Access-токен отозвать нельзя (он самодостаточен и живёт 30 минут), но без
    refresh новый access получить уже не удастся.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = LogoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            token = RefreshToken(serializer.validated_data['refresh'])
        except TokenError:  # просрочен, подделан или уже в чёрном списке
            return Response({'refresh': ['Token is invalid or expired.']},
                            status=status.HTTP_400_BAD_REQUEST)

        # Нельзя разлогинить чужую сессию, зная чужой refresh-токен.
        if str(token['user_id']) != str(request.user.id):
            return Response({'detail': 'This token does not belong to you.'},
                            status=status.HTTP_403_FORBIDDEN)

        token.blacklist()
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeView(RetrieveAPIView):
    serializer_class = UserSerializer
    permission_classes = [IsAuthenticated]

    def get_object(self):
        # Пользователь уже определён по токену; id в URL не нужен.
        return self.request.user
