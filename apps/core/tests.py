from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

from django.contrib.auth.models import Group, Permission
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

def make_user(email, roles=Role.TENANT, **extra):
    """roles — имя роли или список имён: make_user('a@x.com', Role.LANDLORD)
    или make_user('a@x.com', [Role.TENANT, Role.LANDLORD]). Роли = группы,
    созданные миграцией users/0002 (в тестовой базе они уже есть)."""
    user = User.objects.create_user(
        email=email, password=PASSWORD, first_name='Test', last_name='User', **extra
    )
    user.add_roles(*([roles] if isinstance(roles, str) else roles))
    return user


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
    """Для тестов с потоками: транзакции реально коммитятся, как в боевой работе.

    serialized_rollback: после каждого такого теста таблицы очищаются (flush), а вместе с
    ними исчезли бы группы-роли и их права, созданные миграцией. Этот флаг заставляет
    Django восстановить данные миграций перед следующим тестом.
    """

    serialized_rollback = True


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


# ------------------------------------------------- роли = группы + permissions

def payload_for_listing():
    return {'title': 'Cosy flat', 'description': 'A cosy flat in the city centre for guests.',
            'city': 'Berlin', 'address': 'Str. 1', 'price': '90.00', 'rooms': 2, 'housing_type': 'apartment'}


def day_iso(offset):
    return (timezone.localdate() + timedelta(days=offset)).isoformat()


def revoke(role, perm):
    """Забрать у группы-роли право 'приложение.действие_модель' (как это сделал бы админ)."""
    app_label, codename = perm.split('.')
    Group.objects.get(name=role).permissions.remove(
        Permission.objects.get(content_type__app_label=app_label, codename=codename))


class RoleGroupsMigrationTests(BaseAPITestCase):
    """Группы и права создаёт миграция users/0002: в тестовой базе они уже должны быть."""

    EXPECTED = {
        'landlord': {'listings.add_listing', 'listings.change_listing', 'listings.delete_listing',
                     'bookings.change_booking'},
        'tenant': {'bookings.add_booking', 'reviews.add_review'},
    }

    def test_groups_have_exactly_the_expected_permissions(self):
        for name, expected in self.EXPECTED.items():
            with self.subTest(group=name):
                group = Group.objects.get(name=name)
                got = {f'{p.content_type.app_label}.{p.codename}'
                       for p in group.permissions.select_related('content_type')}
                self.assertEqual(got, expected)


class MultiRoleTests(BaseAPITestCase):
    def test_user_with_two_roles_lists_and_books_someone_elses_listing(self):
        both = make_user('both@example.com', [Role.TENANT, Role.LANDLORD])
        owner = make_user('owner@example.com', Role.LANDLORD)

        created = client_for(both).post(f'{API}listings/', payload_for_listing(), format='json')
        self.assertEqual(created.status_code, 201)

        foreign = make_listing(owner)
        booked = client_for(both).post(f'{API}bookings/', {
            'listing': str(foreign.pk), 'start_date': day_iso(10), 'end_date': day_iso(12)}, format='json')
        self.assertEqual(booked.status_code, 201)

        # Своё же жильё он по-прежнему бронировать не может (правило владельца, а не роли).
        own = client_for(both).post(f'{API}bookings/', {
            'listing': created.json()['id'], 'start_date': day_iso(10), 'end_date': day_iso(12)}, format='json')
        self.assertEqual(own.status_code, 400)

        # А как арендодатель он подтверждает заявки на своё жильё.
        guest = make_user('guest@example.com')
        booking = make_booking(Listing.objects.get(pk=created.json()['id']), guest, 5, 7)
        self.assertEqual(client_for(both).patch(f'{API}bookings/{booking.pk}/confirm/').status_code, 200)

    def test_tenant_adds_landlord_role_and_can_then_create_listing(self):
        user = make_user('grow@example.com', Role.TENANT)
        client = client_for(user)
        before = client.post(f'{API}listings/', payload_for_listing(), format='json')
        self.assertEqual(before.status_code, 403)

        self.assertEqual(client.post(f'{API}auth/me/roles/', {'role': 'landlord'}, format='json').status_code, 200)

        # Тот же самый токен: права берутся из БД, а не из claim в токене.
        after = client.post(f'{API}listings/', payload_for_listing(), format='json')
        self.assertEqual(after.status_code, 201)


class PermissionsComeFromGroupsTests(BaseAPITestCase):
    """Если у группы забрать право, действие сразу даёт 403: проверяется именно право, не имя группы."""

    def setUp(self):
        self.landlord = make_user('landlord@example.com', Role.LANDLORD)
        self.tenant = make_user('tenant@example.com', Role.TENANT)
        self.listing = make_listing(self.landlord)

    def booking_payload(self):
        return {'listing': str(self.listing.pk), 'start_date': day_iso(10), 'end_date': day_iso(12)}

    def test_add_listing(self):
        client = client_for(self.landlord)
        self.assertEqual(client.post(f'{API}listings/', payload_for_listing(), format='json').status_code, 201)
        revoke('landlord', 'listings.add_listing')
        self.assertEqual(client.post(f'{API}listings/', payload_for_listing(), format='json').status_code, 403)
        self.assertEqual(client.get(f'{API}listings/my/').status_code, 403)

    def test_change_listing_covers_put_patch_and_toggle(self):
        client = client_for(self.landlord)
        url = f'{API}listings/{self.listing.pk}/'
        revoke('landlord', 'listings.change_listing')
        self.assertEqual(client.patch(url, {'title': 'New title here'}, format='json').status_code, 403)
        self.assertEqual(client.patch(f'{url}toggle-status/', {}, format='json').status_code, 403)
        self.assertEqual(client.get(url).status_code, 200)  # чтение остаётся публичным

    def test_delete_listing(self):
        revoke('landlord', 'listings.delete_listing')
        self.assertEqual(client_for(self.landlord).delete(f'{API}listings/{self.listing.pk}/').status_code, 403)
        self.assertTrue(Listing.objects.filter(pk=self.listing.pk).exists())

    def test_permission_alone_is_not_enough_without_ownership(self):
        other = make_user('other@example.com', Role.LANDLORD)
        response = client_for(other).patch(f'{API}listings/{self.listing.pk}/', {'title': 'Hijacked!'}, format='json')
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()['detail'], 'Only the owner can modify this object.')

    def test_add_booking(self):
        revoke('tenant', 'bookings.add_booking')
        client = client_for(self.tenant)
        self.assertEqual(client.post(f'{API}bookings/', self.booking_payload(), format='json').status_code, 403)
        self.assertEqual(client.get(f'{API}bookings/').status_code, 403)

    def test_change_booking_blocks_confirm_reject_and_requests(self):
        booking = make_booking(self.listing, self.tenant, 5, 7)
        revoke('landlord', 'bookings.change_booking')
        client = client_for(self.landlord)
        self.assertEqual(client.get(f'{API}bookings/requests/').status_code, 403)
        self.assertEqual(client.patch(f'{API}bookings/{booking.pk}/confirm/').status_code, 403)
        self.assertEqual(client.patch(f'{API}bookings/{booking.pk}/reject/').status_code, 403)
        booking.refresh_from_db()
        self.assertEqual(booking.status, BookingStatus.PENDING)

    def test_add_review(self):
        make_booking(self.listing, self.tenant, -10, -7, BookingStatus.CONFIRMED)
        url = f'{API}listings/{self.listing.pk}/reviews/'
        revoke('tenant', 'reviews.add_review')
        response = client_for(self.tenant).post(url, {'rating': 5, 'comment': 'Wonderful flat, very clean and quiet.'},
                                                format='json')
        self.assertEqual(response.status_code, 403)
        self.assertEqual(APIClient().get(url).status_code, 200)

    def test_superuser_passes_every_check(self):
        admin = User.objects.create_superuser('root@example.com', 'x-secret-pass-1', first_name='R', last_name='R')
        self.assertEqual(client_for(admin).post(f'{API}listings/', payload_for_listing(), format='json').status_code, 201)

    def test_inactive_user_has_no_permissions(self):
        self.landlord.is_active = False
        self.landlord.save()
        self.assertFalse(User.objects.get(pk=self.landlord.pk).has_perm('listings.add_listing'))
