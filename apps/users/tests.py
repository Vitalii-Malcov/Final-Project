from rest_framework.test import APIClient
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken
from rest_framework_simplejwt.tokens import AccessToken

from apps.core.tests import API, PASSWORD, BaseAPITestCase, client_for, make_user
from apps.users.choices.roles import Role
from apps.users.models import User

REGISTER = f'{API}auth/register/'
LOGIN = f'{API}auth/login/'
REFRESH = f'{API}auth/refresh/'
LOGOUT = f'{API}auth/logout/'
ME = f'{API}auth/me/'


def register_payload(**overrides):
    data = {'first_name': 'Anna', 'last_name': 'Berg', 'email': 'anna@example.com', 'phone': '+491234',
            'role': 'tenant', 'password': PASSWORD, 're_password': PASSWORD}
    data.update(overrides)
    return data


class UserManagerTests(BaseAPITestCase):
    def test_create_user_lowercases_email_and_hashes_password(self):
        user = User.objects.create_user('Bob@Example.COM', 'secret-pass-1', first_name='B', last_name='B')
        self.assertEqual(user.email, 'bob@example.com')
        self.assertNotEqual(user.password, 'secret-pass-1')       # в БД не открытый текст
        self.assertTrue(user.check_password('secret-pass-1'))
        self.assertFalse(user.is_staff or user.is_superuser)

    def test_create_user_requires_email(self):
        with self.assertRaises(ValueError):
            User.objects.create_user('', 'x')

    def test_create_superuser(self):
        admin = User.objects.create_superuser('root@example.com', 'secret-pass-1', first_name='R', last_name='R')
        self.assertTrue(admin.is_staff and admin.is_superuser)
        self.assertEqual(admin.role, Role.LANDLORD)

    def test_create_superuser_rejects_wrong_flags(self):
        with self.assertRaises(ValueError):
            User.objects.create_superuser('r@example.com', 'x', is_staff=False)

    def test_primary_key_is_uuid7(self):
        user = make_user('uuid@example.com')
        self.assertEqual(user.pk.version, 7)


class RegisterTests(BaseAPITestCase):
    def test_register_without_token_returns_201(self):
        # Главная ловушка этапа: у view явный AllowAny, иначе дефолтный IsAuthenticated дал бы 401.
        response = APIClient().post(REGISTER, register_payload(), format='json')
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body['email'], 'anna@example.com')
        self.assertEqual(body['role'], 'tenant')
        self.assertNotIn('password', body)
        self.assertNotIn('re_password', body)

    def test_register_with_garbage_token_still_works(self):
        response = APIClient().post(REGISTER, register_payload(), format='json', HTTP_AUTHORIZATION='Bearer garbage')
        self.assertEqual(response.status_code, 201)

    def test_email_is_stored_lowercase_and_password_hashed(self):
        self.client.post(REGISTER, register_payload(email='Anna.B@Example.COM'), format='json')
        user = User.objects.get(email='anna.b@example.com')
        self.assertTrue(user.check_password(PASSWORD))
        self.assertNotEqual(user.password, PASSWORD)

    def test_both_roles_can_register(self):
        for i, role in enumerate(('tenant', 'landlord')):
            with self.subTest(role=role):
                r = self.client.post(REGISTER, register_payload(email=f'r{i}@example.com', role=role), format='json')
                self.assertEqual((r.status_code, r.json()['role']), (201, role))

    def test_duplicate_email_is_rejected_case_insensitively(self):
        self.client.post(REGISTER, register_payload(), format='json')
        response = self.client.post(REGISTER, register_payload(email='ANNA@example.com'), format='json')
        self.assertEqual(response.status_code, 400)
        self.assertIn('email', response.json())

    def test_passwords_must_match(self):
        response = self.client.post(REGISTER, register_payload(re_password='different-pass-1'), format='json')
        self.assertEqual(response.status_code, 400)
        self.assertIn('re_password', response.json())

    def test_weak_passwords_are_rejected(self):
        for weak in ('12345678', 'password', 'short1', 'anna@example.com'):
            with self.subTest(password=weak):
                response = self.client.post(REGISTER, register_payload(password=weak, re_password=weak), format='json')
                self.assertEqual(response.status_code, 400)
                self.assertIn('password', response.json())

    def test_invalid_role_and_missing_fields(self):
        self.assertEqual(self.client.post(REGISTER, register_payload(role='admin'), format='json').status_code, 400)
        for field in ('first_name', 'last_name', 'email', 'role', 'password', 're_password'):
            with self.subTest(missing=field):
                payload = register_payload()
                payload.pop(field)
                self.assertEqual(self.client.post(REGISTER, payload, format='json').status_code, 400)

    def test_invalid_email_format(self):
        self.assertEqual(self.client.post(REGISTER, register_payload(email='not-an-email'), format='json').status_code, 400)

    def test_cannot_register_as_staff(self):
        # Лишние поля в теле игнорируются: права через регистрацию получить нельзя.
        self.client.post(REGISTER, register_payload(is_staff=True, is_superuser=True), format='json')
        user = User.objects.get(email='anna@example.com')
        self.assertFalse(user.is_staff or user.is_superuser)


class LoginTests(BaseAPITestCase):
    def setUp(self):
        self.user = make_user('login@example.com', Role.LANDLORD)

    def test_login_without_token_returns_tokens_and_user(self):
        response = APIClient().post(LOGIN, {'email': 'login@example.com', 'password': PASSWORD}, format='json')
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual({'access', 'refresh', 'user'}, set(body))
        self.assertEqual((body['user']['email'], body['user']['role']), ('login@example.com', 'landlord'))
        self.assertNotIn('password', body['user'])

    def test_role_is_in_token_payload(self):
        body = self.client.post(LOGIN, {'email': 'login@example.com', 'password': PASSWORD}, format='json').json()
        self.assertEqual(AccessToken(body['access'])['role'], 'landlord')

    def test_email_is_case_insensitive(self):
        response = self.client.post(LOGIN, {'email': 'LOGIN@Example.com', 'password': PASSWORD}, format='json')
        self.assertEqual(response.status_code, 200)

    def test_wrong_password_and_unknown_user(self):
        for creds in ({'email': 'login@example.com', 'password': 'wrong'},
                      {'email': 'nobody@example.com', 'password': PASSWORD}):
            with self.subTest(creds=creds):
                self.assertEqual(self.client.post(LOGIN, creds, format='json').status_code, 401)

    def test_inactive_user_cannot_login(self):
        self.user.is_active = False
        self.user.save()
        self.assertEqual(self.client.post(LOGIN, {'email': 'login@example.com', 'password': PASSWORD}, format='json').status_code, 401)

    def test_missing_fields(self):
        self.assertEqual(self.client.post(LOGIN, {'email': 'login@example.com'}, format='json').status_code, 400)


class MeTests(BaseAPITestCase):
    def test_me_returns_current_user(self):
        user = make_user('me@example.com')
        body = client_for(user).get(ME).json()
        self.assertEqual((body['email'], body['id']), ('me@example.com', str(user.pk)))
        self.assertNotIn('password', body)

    def test_me_requires_token(self):
        self.assertEqual(APIClient().get(ME).status_code, 401)


class RefreshAndLogoutTests(BaseAPITestCase):
    def setUp(self):
        self.user = make_user('tok@example.com')
        self.tokens = self.client.post(LOGIN, {'email': 'tok@example.com', 'password': PASSWORD}, format='json').json()

    def test_refresh_without_access_token_rotates_refresh(self):
        response = APIClient().post(REFRESH, {'refresh': self.tokens['refresh']}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertIn('access', response.json())
        self.assertNotEqual(response.json()['refresh'], self.tokens['refresh'])  # ROTATE_REFRESH_TOKENS

    def test_old_refresh_is_blacklisted_after_rotation(self):
        APIClient().post(REFRESH, {'refresh': self.tokens['refresh']}, format='json')
        again = APIClient().post(REFRESH, {'refresh': self.tokens['refresh']}, format='json')
        self.assertEqual(again.status_code, 401)  # BLACKLIST_AFTER_ROTATION

    def test_refresh_with_garbage_is_401(self):
        self.assertEqual(self.client.post(REFRESH, {'refresh': 'garbage'}, format='json').status_code, 401)

    def test_logout_blacklists_refresh(self):
        client = client_for(self.user)
        self.assertEqual(client.post(LOGOUT, {'refresh': self.tokens['refresh']}, format='json').status_code, 204)
        self.assertEqual(BlacklistedToken.objects.count(), 1)
        self.assertEqual(APIClient().post(REFRESH, {'refresh': self.tokens['refresh']}, format='json').status_code, 401)

    def test_logout_twice_is_400(self):
        client = client_for(self.user)
        client.post(LOGOUT, {'refresh': self.tokens['refresh']}, format='json')
        self.assertEqual(client.post(LOGOUT, {'refresh': self.tokens['refresh']}, format='json').status_code, 400)

    def test_logout_with_someone_elses_refresh_is_403(self):
        other = make_user('other@example.com')
        other_tokens = self.client.post(LOGIN, {'email': 'other@example.com', 'password': PASSWORD}, format='json').json()
        response = client_for(self.user).post(LOGOUT, {'refresh': other_tokens['refresh']}, format='json')
        self.assertEqual(response.status_code, 403)
        self.assertEqual(BlacklistedToken.objects.count(), 0)  # чужая сессия не тронута
        self.assertTrue(other.is_active)

    def test_logout_validation(self):
        client = client_for(self.user)
        self.assertEqual(client.post(LOGOUT, {}, format='json').status_code, 400)
        self.assertEqual(client.post(LOGOUT, {'refresh': 'garbage'}, format='json').status_code, 400)

    def test_logout_requires_access_token(self):
        response = APIClient().post(LOGOUT, {'refresh': self.tokens['refresh']}, format='json')
        self.assertEqual(response.status_code, 401)
