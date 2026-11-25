import threading
from datetime import timedelta
from decimal import Decimal

from django.db import connections
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.bookings.choices.statuses import BookingStatus
from apps.bookings.models import Booking
from apps.core.tests import (
    API,
    BaseAPITestCase,
    BaseAPITransactionTestCase,
    client_for,
    make_booking,
    make_listing,
    make_user,
)
from apps.users.choices.roles import Role

BOOKINGS = f'{API}bookings/'


def day(offset):
    return (timezone.localdate() + timedelta(days=offset)).isoformat()


def url(booking, action=''):
    return f'{BOOKINGS}{booking.pk}/{action}'


class BookingTestBase(BaseAPITestCase):
    def setUp(self):
        self.landlord = make_user('landlord@example.com', Role.LANDLORD)
        self.other_landlord = make_user('landlord2@example.com', Role.LANDLORD)
        self.tenant = make_user('tenant@example.com')
        self.tenant2 = make_user('tenant2@example.com')
        self.listing = make_listing(self.landlord, price=Decimal('100.00'))

    def create(self, start, end, user=None, listing=None):
        return client_for(user or self.tenant).post(
            BOOKINGS, {'listing': str((listing or self.listing).pk), 'start_date': day(start), 'end_date': day(end)},
            format='json')


class BookingModelTests(BookingTestBase):
    def test_properties(self):
        booking = make_booking(self.listing, self.tenant, 10, 13)
        self.assertEqual(booking.nights, 3)
        self.assertEqual(booking.cancellation_deadline, timezone.localdate() + timedelta(days=9))
        self.assertFalse(booking.is_completed)

    @override_settings(BOOKING_CANCELLATION_DEADLINE_DAYS=3)
    def test_deadline_comes_from_settings(self):
        booking = make_booking(self.listing, self.tenant, 10, 13)
        self.assertEqual(booking.cancellation_deadline, timezone.localdate() + timedelta(days=7))

    def test_overlapping_queryset(self):
        existing = make_booking(self.listing, self.tenant, 10, 15)
        today = timezone.localdate()

        def overlaps(s, e):
            return Booking.objects.overlapping(today + timedelta(days=s), today + timedelta(days=e)).exists()

        self.assertTrue(overlaps(12, 14))   # внутри
        self.assertTrue(overlaps(8, 11))    # заходит слева
        self.assertTrue(overlaps(14, 20))   # заходит справа
        self.assertTrue(overlaps(5, 30))    # накрывает целиком
        self.assertTrue(overlaps(10, 15))   # совпадает
        self.assertFalse(overlaps(5, 10))   # выезд в день заезда существующей: НЕ пересечение
        self.assertFalse(overlaps(15, 20))  # заезд в день выезда существующей: НЕ пересечение
        self.assertFalse(overlaps(1, 5))
        self.assertTrue(existing.pk)

    def test_active_and_completed_querysets(self):
        make_booking(self.listing, self.tenant, 5, 8, BookingStatus.PENDING)
        make_booking(self.listing, self.tenant, 10, 12, BookingStatus.CONFIRMED)
        make_booking(self.listing, self.tenant, 20, 22, BookingStatus.CANCELLED)
        make_booking(self.listing, self.tenant, -10, -7, BookingStatus.CONFIRMED)
        make_booking(self.listing, self.tenant, -20, -17, BookingStatus.PENDING)
        self.assertEqual(Booking.objects.active().count(), 2)
        self.assertEqual(Booking.objects.completed().count(), 1)
        # Выезд сегодня: бронь уже завершена, а не активна.
        ends_today = make_booking(self.listing, self.tenant, -3, 0, BookingStatus.CONFIRMED)
        self.assertTrue(ends_today.is_completed)
        self.assertIn(ends_today, Booking.objects.completed())
        self.assertNotIn(ends_today, Booking.objects.active())

    def test_database_rejects_end_before_start(self):
        from django.db import IntegrityError, transaction
        with self.assertRaises(IntegrityError), transaction.atomic():
            Booking.objects.create(listing=self.listing, tenant=self.tenant, start_date=timezone.localdate(),
                                   end_date=timezone.localdate(), total_price=1)


class BookingCreateTests(BookingTestBase):
    def test_tenant_creates_booking_with_fixed_price(self):
        response = self.create(10, 13)
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual((body['nights'], body['total_price'], body['status']), (3, '300.00', 'pending'))
        self.assertEqual(body['cancellation_deadline'], day(9))
        self.assertEqual(body['tenant']['id'], str(self.tenant.pk))
        self.assertNotIn('email', body['tenant'])
        self.assertEqual(body['listing']['id'], str(self.listing.pk))

    def test_total_price_is_not_taken_from_body_and_is_frozen(self):
        body = client_for(self.tenant).post(
            BOOKINGS, {'listing': str(self.listing.pk), 'start_date': day(10), 'end_date': day(12),
                       'total_price': '1.00', 'status': 'confirmed', 'tenant': str(self.tenant2.pk)},
            format='json').json()
        self.assertEqual((body['total_price'], body['status'], body['tenant']['id']), ('200.00', 'pending', str(self.tenant.pk)))
        # Цена объявления выросла — договорённая сумма брони не меняется.
        self.listing.price = Decimal('999.00')
        self.listing.save()
        self.assertEqual(client_for(self.tenant).get(f"{BOOKINGS}{body['id']}/").json()['total_price'], '200.00')

    def test_price_with_decimals(self):
        listing = make_listing(self.landlord, price=Decimal('33.33'))
        self.assertEqual(self.create(10, 13, listing=listing).json()['total_price'], '99.99')

    def test_date_validation(self):
        cases = {'start in the past': (-2, 3), 'end equals start': (20, 20), 'end before start': (20, 18),
                 '366 nights': (30, 30 + 366), 'whole range in the past': (-10, -5)}
        for label, (start, end) in cases.items():
            with self.subTest(label):
                self.assertEqual(self.create(start, end).status_code, 400)

    def test_boundaries_are_accepted(self):
        self.assertEqual(self.create(0, 1).status_code, 201)           # заезд сегодня
        self.assertEqual(self.create(100, 100 + 365).status_code, 201)  # ровно 365 ночей

    def test_bad_input(self):
        client = client_for(self.tenant)
        self.assertEqual(client.post(BOOKINGS, {'listing': str(self.listing.pk), 'start_date': 'tomorrow', 'end_date': day(5)}, format='json').status_code, 400)
        self.assertEqual(client.post(BOOKINGS, {}, format='json').status_code, 400)
        self.assertEqual(client.post(BOOKINGS, {'listing': 'not-a-uuid', 'start_date': day(1), 'end_date': day(2)}, format='json').status_code, 400)
        unknown = '019a0000-0000-7000-8000-000000000000'
        self.assertEqual(client.post(BOOKINGS, {'listing': unknown, 'start_date': day(1), 'end_date': day(2)}, format='json').status_code, 400)

    def test_cannot_book_inactive_listing(self):
        hidden = make_listing(self.landlord, is_active=False)
        self.assertEqual(self.create(10, 12, listing=hidden).status_code, 400)

    def test_cannot_book_own_listing(self):
        # Без роли арендатора владелец получил бы 403; чтобы проверить само правило, добавляем ему группу tenant.
        self.landlord.add_roles(Role.TENANT)
        response = self.create(10, 12, user=self.landlord)
        self.assertEqual(response.status_code, 400)
        self.assertIn('listing', response.json())

    def test_only_tenants_can_create(self):
        self.assertEqual(self.create(10, 12, user=self.other_landlord).status_code, 403)
        self.assertEqual(APIClient().post(BOOKINGS, {}, format='json').status_code, 401)


class BookingOverlapTests(BookingTestBase):
    def test_overlap_with_confirmed_booking_is_409(self):
        make_booking(self.listing, self.tenant2, 10, 15, BookingStatus.CONFIRMED)
        for start, end in ((12, 14), (8, 11), (14, 20), (5, 30), (10, 15)):
            with self.subTest(start=start, end=end):
                self.assertEqual(self.create(start, end).status_code, 409)

    def test_adjacent_dates_with_confirmed_are_allowed(self):
        make_booking(self.listing, self.tenant2, 10, 15, BookingStatus.CONFIRMED)
        self.assertEqual(self.create(15, 17).status_code, 201)  # заезд в день выезда
        self.assertEqual(self.create(5, 10).status_code, 201)   # выезд в день заезда

    def test_own_overlapping_pending_is_409(self):
        make_booking(self.listing, self.tenant, 10, 15)
        self.assertEqual(self.create(12, 18).status_code, 409)
        self.assertEqual(self.create(10, 15).status_code, 409)

    def test_own_adjacent_pending_is_ok(self):
        make_booking(self.listing, self.tenant, 10, 13)
        self.assertEqual(self.create(13, 15).status_code, 201)

    def test_another_tenants_pending_does_not_block(self):
        make_booking(self.listing, self.tenant2, 10, 15)
        self.assertEqual(self.create(12, 14).status_code, 201)

    def test_cancelled_and_rejected_do_not_block(self):
        make_booking(self.listing, self.tenant2, 10, 15, BookingStatus.CANCELLED)
        make_booking(self.listing, self.tenant2, 10, 15, BookingStatus.REJECTED)
        make_booking(self.listing, self.tenant, 10, 15, BookingStatus.CANCELLED)
        self.assertEqual(self.create(11, 13).status_code, 201)

    def test_confirmed_on_another_listing_does_not_block(self):
        other = make_listing(self.landlord)
        make_booking(other, self.tenant2, 10, 15, BookingStatus.CONFIRMED)
        self.assertEqual(self.create(11, 13).status_code, 201)

    def test_conflict_error_message(self):
        make_booking(self.listing, self.tenant2, 10, 15, BookingStatus.CONFIRMED)
        self.assertIn('already booked', self.create(11, 13).json()['detail'])


class BookingConfirmRejectTests(BookingTestBase):
    def confirm(self, booking, user=None):
        return client_for(user or self.landlord).patch(url(booking, 'confirm/'))

    def reject(self, booking, user=None):
        return client_for(user or self.landlord).patch(url(booking, 'reject/'))

    def status_of(self, booking):
        booking.refresh_from_db()
        return booking.status

    def test_owner_confirms_pending(self):
        booking = make_booking(self.listing, self.tenant, 10, 13)
        response = self.confirm(booking)
        self.assertEqual((response.status_code, response.json()['status']), (200, 'confirmed'))

    def test_confirm_auto_rejects_overlapping_pending_only(self):
        main = make_booking(self.listing, self.tenant, 10, 15)
        overlapping = make_booking(self.listing, self.tenant2, 12, 18)
        adjacent = make_booking(self.listing, self.tenant2, 15, 17)      # смежная: не пересекается
        far = make_booking(self.listing, self.tenant2, 40, 45)
        other_listing = make_booking(make_listing(self.landlord), self.tenant2, 11, 14)
        cancelled = make_booking(self.listing, self.tenant2, 11, 13, BookingStatus.CANCELLED)
        self.assertEqual(self.confirm(main).status_code, 200)
        self.assertEqual(self.status_of(overlapping), 'rejected')
        self.assertEqual(self.status_of(adjacent), 'pending')
        self.assertEqual(self.status_of(far), 'pending')
        self.assertEqual(self.status_of(other_listing), 'pending')       # другое объявление не затронуто
        self.assertEqual(self.status_of(cancelled), 'cancelled')         # отменённые не трогаем

    def test_auto_reject_updates_updated_at(self):
        main = make_booking(self.listing, self.tenant, 10, 15)
        victim = make_booking(self.listing, self.tenant2, 12, 18)
        before = victim.updated_at
        self.confirm(main)
        victim.refresh_from_db()
        self.assertGreater(victim.updated_at, before)  # update() не вызывает auto_now: ставим вручную

    def test_confirm_conflicting_with_confirmed_is_409_and_changes_nothing(self):
        make_booking(self.listing, self.tenant2, 10, 15, BookingStatus.CONFIRMED)
        # Такая пара могла появиться только в гонке: проверяем защиту самого confirm.
        ghost = make_booking(self.listing, self.tenant, 12, 14)
        sibling = make_booking(self.listing, self.tenant2, 20, 22)
        response = self.confirm(ghost)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.status_of(ghost), 'pending')    # транзакция откатилась
        self.assertEqual(self.status_of(sibling), 'pending')

    def test_confirm_only_pending(self):
        for status_ in (BookingStatus.CONFIRMED, BookingStatus.REJECTED, BookingStatus.CANCELLED):
            with self.subTest(status=status_):
                booking = make_booking(self.listing, self.tenant, 10, 13, status_)
                self.assertEqual(self.confirm(booking).status_code, 409)
                booking.delete()

    def test_cannot_confirm_booking_that_already_started(self):
        booking = make_booking(self.listing, self.tenant, -2, 3)
        self.assertEqual(self.confirm(booking).status_code, 409)

    def test_confirm_permissions(self):
        booking = make_booking(self.listing, self.tenant, 10, 13)
        self.assertEqual(self.confirm(booking, self.tenant).status_code, 403)             # арендатор
        self.assertEqual(self.confirm(booking, self.other_landlord).status_code, 404)     # чужой арендодатель
        self.assertEqual(APIClient().patch(url(booking, 'confirm/')).status_code, 401)
        self.assertEqual(self.status_of(booking), 'pending')

    def test_reject_pending(self):
        booking = make_booking(self.listing, self.tenant, 10, 13)
        response = self.reject(booking)
        self.assertEqual((response.status_code, response.json()['status']), (200, 'rejected'))
        self.assertEqual(self.reject(booking).status_code, 409)   # повторно нельзя

    def test_reject_only_pending(self):
        for status_ in (BookingStatus.CONFIRMED, BookingStatus.CANCELLED):
            with self.subTest(status=status_):
                booking = make_booking(self.listing, self.tenant, 10, 13, status_)
                self.assertEqual(self.reject(booking).status_code, 409)
                booking.delete()

    def test_reject_permissions(self):
        booking = make_booking(self.listing, self.tenant, 10, 13)
        self.assertEqual(self.reject(booking, self.tenant).status_code, 403)
        self.assertEqual(self.reject(booking, self.other_landlord).status_code, 404)
        self.assertEqual(APIClient().patch(url(booking, 'reject/')).status_code, 401)

    def test_rejected_dates_become_free(self):
        booking = make_booking(self.listing, self.tenant2, 10, 13)
        self.reject(booking)
        self.assertEqual(self.create(10, 13).status_code, 201)

    def test_confirmed_booking_blocks_new_requests_for_its_dates(self):
        booking = make_booking(self.listing, self.tenant2, 10, 13)
        self.confirm(booking)
        self.assertEqual(self.create(11, 12).status_code, 409)

    def test_confirmed_booking_can_be_followed_by_adjacent_one(self):
        first = make_booking(self.listing, self.tenant, 10, 13)
        second = make_booking(self.listing, self.tenant2, 13, 16)
        self.assertEqual(self.confirm(first).status_code, 200)
        self.assertEqual(self.confirm(second).status_code, 200)  # смежные даты — не конфликт


class BookingCancelTests(BookingTestBase):
    def cancel(self, booking, user=None):
        return client_for(user or self.tenant).patch(url(booking, 'cancel/'))

    def test_cancel_pending_and_confirmed(self):
        for status_ in (BookingStatus.PENDING, BookingStatus.CONFIRMED):
            with self.subTest(status=status_):
                booking = make_booking(self.listing, self.tenant, 10, 13, status_)
                response = self.cancel(booking)
                self.assertEqual((response.status_code, response.json()['status']), (200, 'cancelled'))
                booking.delete()

    @override_settings(BOOKING_CANCELLATION_DEADLINE_DAYS=1)
    def test_deadline_boundary(self):
        # Заезд завтра, дедлайн «сегодня»: последний допустимый день, отмена ещё можно.
        self.assertEqual(self.cancel(make_booking(self.listing, self.tenant, 1, 3)).status_code, 200)
        # Заезд сегодня, дедлайн вчера: поздно.
        late = make_booking(self.listing, self.tenant, 0, 2)
        response = self.cancel(late)
        self.assertEqual(response.status_code, 409)
        self.assertIn('deadline', response.json()['detail'])
        late.refresh_from_db()
        self.assertEqual(late.status, 'pending')

    @override_settings(BOOKING_CANCELLATION_DEADLINE_DAYS=5)
    def test_deadline_is_configurable(self):
        self.assertEqual(self.cancel(make_booking(self.listing, self.tenant, 5, 8)).status_code, 200)
        self.assertEqual(self.cancel(make_booking(self.listing, self.tenant, 4, 8)).status_code, 409)

    def test_cannot_cancel_finished_or_ongoing(self):
        self.assertEqual(self.cancel(make_booking(self.listing, self.tenant, -10, -7, BookingStatus.CONFIRMED)).status_code, 409)
        self.assertEqual(self.cancel(make_booking(self.listing, self.tenant, -1, 3, BookingStatus.CONFIRMED)).status_code, 409)

    def test_cannot_cancel_in_wrong_status(self):
        for status_ in (BookingStatus.CANCELLED, BookingStatus.REJECTED):
            with self.subTest(status=status_):
                booking = make_booking(self.listing, self.tenant, 10, 13, status_)
                self.assertEqual(self.cancel(booking).status_code, 409)
                booking.delete()

    def test_cancel_permissions(self):
        booking = make_booking(self.listing, self.tenant, 10, 13)
        self.assertEqual(self.cancel(booking, self.tenant2).status_code, 404)        # чужая бронь
        self.assertEqual(self.cancel(booking, self.landlord).status_code, 403)       # арендодатель
        self.assertEqual(APIClient().patch(url(booking, 'cancel/')).status_code, 401)

    def test_cancel_frees_dates_for_others(self):
        confirmed = make_booking(self.listing, self.tenant, 10, 13, BookingStatus.CONFIRMED)
        self.assertEqual(self.create(11, 12, user=self.tenant2).status_code, 409)
        self.cancel(confirmed)
        self.assertEqual(self.create(11, 12, user=self.tenant2).status_code, 201)


class BookingReadTests(BookingTestBase):
    def test_detail_visible_to_tenant_and_listing_owner_only(self):
        booking = make_booking(self.listing, self.tenant, 10, 13)
        self.assertEqual(client_for(self.tenant).get(url(booking)).status_code, 200)
        self.assertEqual(client_for(self.landlord).get(url(booking)).status_code, 200)
        self.assertEqual(client_for(self.tenant2).get(url(booking)).status_code, 404)
        self.assertEqual(client_for(self.other_landlord).get(url(booking)).status_code, 404)
        self.assertEqual(APIClient().get(url(booking)).status_code, 401)

    def test_list_contains_only_own_bookings(self):
        mine = make_booking(self.listing, self.tenant, 10, 13)
        make_booking(self.listing, self.tenant2, 20, 23)
        results = client_for(self.tenant).get(BOOKINGS).json()['results']
        self.assertEqual([x['id'] for x in results], [str(mine.pk)])

    def test_state_filters(self):
        pending = make_booking(self.listing, self.tenant, 10, 12, BookingStatus.PENDING)
        confirmed = make_booking(self.listing, self.tenant, 20, 22, BookingStatus.CONFIRMED)
        cancelled = make_booking(self.listing, self.tenant, 30, 32, BookingStatus.CANCELLED)
        rejected = make_booking(self.listing, self.tenant, 40, 42, BookingStatus.REJECTED)
        finished = make_booking(self.listing, self.tenant, -10, -7, BookingStatus.CONFIRMED)
        client = client_for(self.tenant)

        def ids(state):
            return {x['id'] for x in client.get(f'{BOOKINGS}?state={state}').json()['results']}

        self.assertEqual(ids('active'), {str(pending.pk), str(confirmed.pk)})
        self.assertEqual(ids('completed'), {str(finished.pk)})
        self.assertEqual(ids('cancelled'), {str(cancelled.pk)})
        self.assertEqual(ids('rejected'), {str(rejected.pk)})
        self.assertEqual(len(client.get(BOOKINGS).json()['results']), 5)  # без фильтра — все

    def test_invalid_state_is_400(self):
        self.assertEqual(client_for(self.tenant).get(f'{BOOKINGS}?state=bogus').status_code, 400)

    def test_is_completed_flag_in_response(self):
        finished = make_booking(self.listing, self.tenant, -10, -7, BookingStatus.CONFIRMED)
        self.assertTrue(client_for(self.tenant).get(url(finished)).json()['is_completed'])

    def test_list_permissions(self):
        self.assertEqual(client_for(self.landlord).get(BOOKINGS).status_code, 403)
        self.assertEqual(APIClient().get(BOOKINGS).status_code, 401)

    def test_landlord_requests_only_for_own_listings(self):
        mine = make_booking(self.listing, self.tenant, 10, 13)
        make_booking(make_listing(self.other_landlord), self.tenant, 10, 13)
        results = client_for(self.landlord).get(f'{BOOKINGS}requests/').json()['results']
        self.assertEqual([x['id'] for x in results], [str(mine.pk)])
        self.assertEqual(client_for(self.other_landlord).get(f'{BOOKINGS}requests/').json()['count'], 1)

    def test_requests_status_filter(self):
        make_booking(self.listing, self.tenant, 10, 12, BookingStatus.PENDING)
        make_booking(self.listing, self.tenant, 20, 22, BookingStatus.CONFIRMED)
        client = client_for(self.landlord)
        self.assertEqual(client.get(f'{BOOKINGS}requests/?status=pending').json()['count'], 1)
        self.assertEqual(client.get(f'{BOOKINGS}requests/?status=confirmed').json()['count'], 1)
        self.assertEqual(client.get(f'{BOOKINGS}requests/?status=rejected').json()['count'], 0)
        self.assertEqual(client.get(f'{BOOKINGS}requests/?status=bogus').status_code, 400)

    def test_requests_permissions(self):
        self.assertEqual(client_for(self.tenant).get(f'{BOOKINGS}requests/').status_code, 403)
        self.assertEqual(APIClient().get(f'{BOOKINGS}requests/').status_code, 401)


class ConcurrentConfirmTests(BaseAPITransactionTestCase):
    """Гонка: владелец (двойной клик, два устройства) одновременно подтверждает ДВЕ пересекающиеся заявки.

    Нужен APITransactionTestCase: обычный TestCase оборачивает тест в одну транзакцию,
    и потоки не увидели бы данные друг друга. Здесь транзакции настоящие, как в боевой работе.
    """

    def test_two_simultaneous_confirms_never_double_book(self):
        landlord = make_user('landlord@example.com', Role.LANDLORD)
        tenant_a, tenant_b = make_user('a@example.com'), make_user('b@example.com')

        for round_number in range(5):
            listing = make_listing(landlord, title=f'Race listing {round_number}')
            first = make_booking(listing, tenant_a, 40, 45)
            second = make_booking(listing, tenant_b, 43, 48)
            barrier, statuses = threading.Barrier(2), []

            def worker(booking):
                try:
                    barrier.wait()  # оба запроса стартуют одновременно
                    statuses.append(client_for(landlord).patch(url(booking, 'confirm/')).status_code)
                finally:
                    connections.close_all()  # соединение потока закрываем сами

            threads = [threading.Thread(target=worker, args=(b,)) for b in (first, second)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            # Ровно один подтверждён, второй получил 409; ни одного 500 (deadlock).
            self.assertEqual(sorted(statuses), [200, 409], f'round {round_number}: {statuses}')
            self.assertEqual(Booking.objects.filter(listing=listing, status=BookingStatus.CONFIRMED).count(), 1)
            self.assertEqual(Booking.objects.filter(listing=listing, status=BookingStatus.REJECTED).count(), 1)
