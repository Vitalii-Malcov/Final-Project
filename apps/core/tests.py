from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

from django.test import RequestFactory, override_settings
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase, APITransactionTestCase
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

from apps.bookings.choices.statuses import BookingStatus
from apps.bookings.models import Booking
from apps.core.views import server_error
from apps.listings.models import Listing
from apps.users.choices.roles import Role
from apps.users.models import User

API = '/api/v1/'
PASSWORD = 'S3cure-pass-Xy!'

# В тестах подменяем хешер паролей на быстрый MD5: боевой PBKDF2 намеренно медленный,
# и сотни create_user замедлили бы набор в разы. Логика паролей при этом та же.
FAST_HASHER = override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])


# ------------------------------------------------------------ общие помощники
# Их импортируют тесты остальных приложений. Классы TestCase отсюда НЕ импортируем
# (только базовые), чтобы тесты не запускались дважды.

def make_user(email, role=Role.TENANT, **extra):
    return User.objects.create_user(
        email=email, password=PASSWORD, first_name='Test', last_name='User', role=role, **extra
    )


def make_listing(owner, **overrides):
    data = {
        'title': 'Nice apartment',
        'description': 'A very nice place to stay, close to everything.',
        'city': 'Berlin', 'district': 'Mitte', 'address': 'Main str. 1',
        'price': Decimal('100.00'), 'rooms': 2, 'housing_type': 'apartment', 'is_active': True,
    }
    data.update(overrides)
    return Listing.objects.create(owner=owner, **data)


def make_booking(listing, tenant, start, end, status=BookingStatus.PENDING):
    """start/end — смещение в днях от сегодняшней даты (отрицательное = прошлое)."""
    today = timezone.localdate()
    start_date, end_date = today + timedelta(days=start), today + timedelta(days=end)
    return Booking.objects.create(
        listing=listing, tenant=tenant, start_date=start_date, end_date=end_date,
        total_price=listing.price * (end_date - start_date).days, status=status,
    )


def bearer(user):
    """НАСТОЯЩИЙ access-токен в заголовке. force_authenticate не годится: он
    пропускает JWT-проверку, а middleware смотрит именно на заголовок."""
    return f'Bearer {AccessToken.for_user(user)}'


def client_for(user=None):
    client = APIClient()
    if user is not None:
        client.credentials(HTTP_AUTHORIZATION=bearer(user))
    return client


@FAST_HASHER
class BaseAPITestCase(APITestCase):
    pass


@FAST_HASHER
class BaseAPITransactionTestCase(APITransactionTestCase):
    """Для тестов с потоками: транзакции реально коммитятся, как в боевой работе."""


# ---------------------------------------------------------------- тесты core

class MiddlewareTests(BaseAPITestCase):
    """Уровень 1 защиты: JWTProtectedRoutesMiddleware."""

    def setUp(self):
        self.user = make_user('user@example.com')
        self.anon = APIClient()

    def test_public_auth_paths_are_not_blocked_by_middleware(self):
        # Пустое тело даёт 400 от валидации, а не 401: до view запрос дошёл без токена.
        for path in ('auth/register/', 'auth/login/', 'auth/refresh/'):
            with self.subTest(path=path):
                self.assertEqual(self.anon.post(f'{API}{path}', {}, format='json').status_code, 400)

    def test_private_get_paths_require_token(self):
        paths = ['auth/me/', 'auth/logout/', 'listings/my/', 'listings/searches/my/',
                 'bookings/', 'bookings/requests/', f'bookings/{uuid4()}/']
        for path in paths:
            with self.subTest(path=path):
                response = self.anon.get(f'{API}{path}')
                self.assertEqual(response.status_code, 401)
                self.assertEqual(response['Content-Type'], 'application/json')

    def test_any_unsafe_method_requires_token(self):
        some_id = uuid4()
        calls = [('post', 'listings/'), ('put', f'listings/{some_id}/'), ('patch', f'listings/{some_id}/'),
                 ('delete', f'listings/{some_id}/'), ('patch', f'listings/{some_id}/toggle-status/'),
                 ('post', 'bookings/'), ('patch', f'bookings/{some_id}/confirm/'),
                 ('post', f'listings/{some_id}/reviews/')]
        for method, path in calls:
            with self.subTest(method=method, path=path):
                self.assertEqual(getattr(self.anon, method)(f'{API}{path}', {}, format='json').status_code, 401)

    def test_public_reads_do_not_require_token(self):
        for path in ('listings/', 'listings/popular/', 'listings/searches/popular/'):
            with self.subTest(path=path):
                self.assertEqual(self.anon.get(f'{API}{path}').status_code, 200)

    def test_garbage_token_is_rejected(self):
        for header in ('Bearer garbage', 'Bearer', 'Token abc', 'garbage'):
            with self.subTest(header=header):
                response = self.anon.get(f'{API}auth/me/', HTTP_AUTHORIZATION=header)
                self.assertEqual(response.status_code, 401)

    def test_refresh_token_cannot_be_used_as_access_token(self):
        refresh = str(RefreshToken.for_user(self.user))
        response = self.anon.get(f'{API}auth/me/', HTTP_AUTHORIZATION=f'Bearer {refresh}')
        self.assertEqual(response.status_code, 401)

    def test_expired_token_is_rejected(self):
        token = AccessToken.for_user(self.user)
        token.set_exp(lifetime=-timedelta(seconds=10))
        response = self.anon.get(f'{API}auth/me/', HTTP_AUTHORIZATION=f'Bearer {token}')
        self.assertEqual(response.status_code, 401)

    def test_token_of_deleted_or_inactive_user_is_rejected(self):
        header = bearer(self.user)
        self.user.is_active = False
        self.user.save()
        self.assertEqual(self.anon.get(f'{API}auth/me/', HTTP_AUTHORIZATION=header).status_code, 401)
        self.user.delete()
        self.assertEqual(self.anon.get(f'{API}auth/me/', HTTP_AUTHORIZATION=header).status_code, 401)

    def test_valid_token_passes(self):
        self.assertEqual(client_for(self.user).get(f'{API}auth/me/').status_code, 200)

    def test_401_response_format(self):
        response = self.anon.get(f'{API}auth/me/')
        self.assertEqual(response.json(), {'detail': 'Authentication credentials were not provided.'})
        self.assertEqual(response['WWW-Authenticate'], 'Bearer')

    def test_admin_is_not_affected(self):
        # Админка вне /api/v1/: у неё своя сессионная защита, middleware её не трогает.
        self.assertEqual(self.anon.get('/admin/login/').status_code, 200)


class ErrorHandlersTests(BaseAPITestCase):
    def test_404_is_json(self):
        # Тесты идут с DEBUG=False, поэтому срабатывает наш handler404.
        response = self.client.get(f'{API}no/such/path/')
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json(), {'detail': 'Not found.'})

    def test_500_handler_is_json(self):
        response = server_error(RequestFactory().get('/'))
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.content, b'{"detail": "Internal server error."}')


class PaginationTests(BaseAPITestCase):
    @classmethod
    def setUpTestData(cls):
        owner = make_user('owner@example.com', Role.LANDLORD)
        Listing.objects.bulk_create([
            Listing(owner=owner, title=f'Listing number {i}', description='x' * 30, city='Berlin',
                    address='a', price=Decimal('10'), rooms=1, housing_type='room')
            for i in range(105)
        ])

    def test_default_page_size_is_10(self):
        data = self.client.get(f'{API}listings/').json()
        self.assertEqual((len(data['results']), data['count']), (10, 105))
        self.assertIsNotNone(data['next'])

    def test_custom_page_size(self):
        self.assertEqual(len(self.client.get(f'{API}listings/?page_size=5').json()['results']), 5)

    def test_page_size_is_capped_at_100(self):
        self.assertEqual(len(self.client.get(f'{API}listings/?page_size=1000').json()['results']), 100)

    def test_page_beyond_the_end_is_404(self):
        self.assertEqual(self.client.get(f'{API}listings/?page=999').status_code, 404)

    def test_pages_do_not_overlap(self):
        ids = []
        for page in range(1, 12):
            ids += [x['id'] for x in self.client.get(f'{API}listings/?page={page}').json()['results']]
        self.assertEqual((len(ids), len(set(ids))), (105, 105))  # стабильный порядок: ничего не потеряно и не повторено
