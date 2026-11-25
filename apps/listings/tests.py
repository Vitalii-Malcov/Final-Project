from decimal import Decimal

from rest_framework.test import APIClient

from apps.bookings.choices.statuses import BookingStatus
from apps.core.tests import (
    API,
    BaseAPITestCase,
    client_for,
    make_booking,
    make_listing,
    make_user,
)
from apps.listings.models import Listing, ListingView, SearchQuery
from apps.reviews.models import Review
from apps.users.choices.roles import Role

LISTINGS = f'{API}listings/'


def detail(listing, suffix=''):
    return f'{LISTINGS}{listing.pk}/{suffix}'


def valid_payload(**overrides):
    data = {'title': 'Cozy flat', 'description': 'Bright flat near the park, five minutes to subway.',
            'city': 'Berlin', 'district': 'Mitte', 'address': 'Main str. 1', 'price': '75.50',
            'rooms': 2, 'housing_type': 'apartment'}
    data.update(overrides)
    return data


def titles(response):
    return [x['title'] for x in response.json()['results']]


class WithStatsTests(BaseAPITestCase):
    """Модельный уровень: Listing.objects.with_stats()."""

    def test_counts_are_not_multiplied_by_each_other(self):
        owner = make_user('o@example.com', Role.LANDLORD)
        listing = make_listing(owner)
        for _ in range(3):
            ListingView.objects.create(listing=listing)
        for i, rating in enumerate((5, 2)):
            Review.objects.create(listing=listing, author=make_user(f'a{i}@example.com'), rating=rating, comment='ok')
        stats = Listing.objects.with_stats().get(pk=listing.pk)
        # JOIN обоих таблиц дал бы 6 строк и завышенные счётчики; Subquery считает независимо.
        self.assertEqual((stats.views_count, stats.reviews_count, stats.avg_rating), (3, 2, 3.5))

    def test_listing_without_views_and_reviews(self):
        listing = make_listing(make_user('o@example.com', Role.LANDLORD))
        stats = Listing.objects.with_stats().get(pk=listing.pk)
        self.assertEqual((stats.views_count, stats.reviews_count), (0, 0))
        self.assertIsNone(stats.avg_rating)  # нет отзывов -> нет средней, а не 0.0

    def test_active_filters_hidden(self):
        owner = make_user('o@example.com', Role.LANDLORD)
        make_listing(owner, title='visible one')
        make_listing(owner, title='hidden one', is_active=False)
        self.assertEqual(list(Listing.objects.active().values_list('title', flat=True)), ['visible one'])


class ListingCreateTests(BaseAPITestCase):
    def setUp(self):
        self.landlord = make_user('landlord@example.com', Role.LANDLORD)
        self.tenant = make_user('tenant@example.com')

    def test_landlord_creates_listing(self):
        response = client_for(self.landlord).post(LISTINGS, valid_payload(), format='json')
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body['owner']['id'], str(self.landlord.pk))
        self.assertEqual((body['views_count'], body['reviews_count'], body['avg_rating']), (0, 0, None))
        self.assertTrue(body['is_active'])
        self.assertNotIn('email', body['owner'])

    def test_owner_comes_from_token_not_from_body(self):
        other = make_user('other@example.com', Role.LANDLORD)
        body = client_for(self.landlord).post(LISTINGS, valid_payload(owner=str(other.pk)), format='json').json()
        self.assertEqual(body['owner']['id'], str(self.landlord.pk))

    def test_tenant_gets_403(self):
        self.assertEqual(client_for(self.tenant).post(LISTINGS, valid_payload(), format='json').status_code, 403)

    def test_anonymous_gets_401(self):
        self.assertEqual(APIClient().post(LISTINGS, valid_payload(), format='json').status_code, 401)

    def test_validation_errors(self):
        bad = {
            'title too short': {'title': 'abc'},
            'description too short': {'description': 'too short'},
            'price zero': {'price': '0'},
            'price negative': {'price': '-5'},
            'price not a number': {'price': 'free'},
            'rooms zero': {'rooms': 0},
            'rooms 51': {'rooms': 51},
            'unknown housing type': {'housing_type': 'castle'},
            'blank city': {'city': ''},
        }
        for label, override in bad.items():
            with self.subTest(label):
                response = client_for(self.landlord).post(LISTINGS, valid_payload(**override), format='json')
                self.assertEqual(response.status_code, 400)

    def test_required_fields(self):
        for field in ('title', 'description', 'city', 'address', 'price', 'rooms', 'housing_type'):
            with self.subTest(missing=field):
                payload = valid_payload()
                payload.pop(field)
                self.assertEqual(client_for(self.landlord).post(LISTINGS, payload, format='json').status_code, 400)

    def test_district_is_optional_and_boundaries_are_accepted(self):
        payload = valid_payload(price='1', rooms=50, title='abcde')
        payload.pop('district')
        self.assertEqual(client_for(self.landlord).post(LISTINGS, payload, format='json').status_code, 201)


class ListingDetailAndVisibilityTests(BaseAPITestCase):
    def setUp(self):
        self.owner = make_user('owner@example.com', Role.LANDLORD)
        self.other = make_user('other@example.com', Role.LANDLORD)
        self.listing = make_listing(self.owner)
        self.hidden = make_listing(self.owner, title='Hidden flat', is_active=False)

    def test_anyone_can_read_active_listing(self):
        self.assertEqual(APIClient().get(detail(self.listing)).status_code, 200)

    def test_inactive_listing_is_hidden_from_everyone_but_owner(self):
        self.assertEqual(APIClient().get(detail(self.hidden)).status_code, 404)
        self.assertEqual(client_for(self.other).get(detail(self.hidden)).status_code, 404)
        self.assertEqual(client_for(self.owner).get(detail(self.hidden)).status_code, 200)

    def test_inactive_listing_is_404_even_for_modification_by_others(self):
        # 404, а не 403: чужому не раскрываем, что такое объявление существует.
        self.assertEqual(client_for(self.other).patch(detail(self.hidden), {'price': '5'}, format='json').status_code, 404)

    def test_unknown_id_is_404(self):
        self.assertEqual(APIClient().get(f'{LISTINGS}019a0000-0000-7000-8000-000000000000/').status_code, 404)

    def test_hidden_listing_not_in_public_list_but_in_my_list(self):
        self.assertEqual(titles(APIClient().get(LISTINGS)), ['Nice apartment'])
        self.assertEqual(client_for(self.owner).get(f'{LISTINGS}my/').json()['count'], 2)


class ListingUpdateDeleteTests(BaseAPITestCase):
    def setUp(self):
        self.owner = make_user('owner@example.com', Role.LANDLORD)
        self.other = make_user('other@example.com', Role.LANDLORD)
        self.tenant = make_user('tenant@example.com')
        self.listing = make_listing(self.owner)

    def test_owner_patches(self):
        response = client_for(self.owner).patch(detail(self.listing), {'price': '55.50'}, format='json')
        self.assertEqual((response.status_code, response.json()['price']), (200, '55.50'))
        self.assertIn('views_count', response.json())  # ответ со статистикой, как и у GET

    def test_owner_puts_full_body_but_not_partial(self):
        client = client_for(self.owner)
        self.assertEqual(client.put(detail(self.listing), valid_payload(city='Hamburg'), format='json').status_code, 200)
        self.listing.refresh_from_db()
        self.assertEqual(self.listing.city, 'Hamburg')
        self.assertEqual(client.put(detail(self.listing), {'title': 'Only title'}, format='json').status_code, 400)

    def test_patch_validates(self):
        self.assertEqual(client_for(self.owner).patch(detail(self.listing), {'rooms': 99}, format='json').status_code, 400)

    def test_owner_cannot_be_changed(self):
        client_for(self.owner).patch(detail(self.listing), {'owner': str(self.other.pk)}, format='json')
        self.listing.refresh_from_db()
        self.assertEqual(self.listing.owner_id, self.owner.pk)

    def test_non_owners_cannot_modify_or_delete(self):
        for who in (self.other, self.tenant):
            client = client_for(who)
            for label, response in {
                'patch': client.patch(detail(self.listing), {'price': '1'}, format='json'),
                'put': client.put(detail(self.listing), valid_payload(), format='json'),
                'delete': client.delete(detail(self.listing)),
            }.items():
                with self.subTest(user=who.email, method=label):
                    self.assertEqual(response.status_code, 403)
        self.assertTrue(Listing.objects.filter(pk=self.listing.pk).exists())

    def test_anonymous_cannot_modify(self):
        self.assertEqual(APIClient().delete(detail(self.listing)).status_code, 401)

    def test_owner_deletes(self):
        self.assertEqual(client_for(self.owner).delete(detail(self.listing)).status_code, 204)
        self.assertFalse(Listing.objects.filter(pk=self.listing.pk).exists())

    def test_cannot_delete_with_future_confirmed_booking(self):
        make_booking(self.listing, self.tenant, 5, 8, BookingStatus.CONFIRMED)
        response = client_for(self.owner).delete(detail(self.listing))
        self.assertEqual(response.status_code, 409)
        self.assertTrue(Listing.objects.filter(pk=self.listing.pk).exists())

    def test_cannot_delete_during_ongoing_confirmed_stay(self):
        make_booking(self.listing, self.tenant, -2, 2, BookingStatus.CONFIRMED)
        self.assertEqual(client_for(self.owner).delete(detail(self.listing)).status_code, 409)

    def test_can_delete_when_bookings_are_not_active_confirmed(self):
        make_booking(self.listing, self.tenant, 5, 8, BookingStatus.PENDING)
        make_booking(self.listing, self.tenant, 10, 12, BookingStatus.CANCELLED)
        make_booking(self.listing, self.tenant, 20, 22, BookingStatus.REJECTED)
        make_booking(self.listing, self.tenant, -10, -7, BookingStatus.CONFIRMED)  # уже завершена
        self.assertEqual(client_for(self.owner).delete(detail(self.listing)).status_code, 204)


class ToggleStatusTests(BaseAPITestCase):
    def setUp(self):
        self.owner = make_user('owner@example.com', Role.LANDLORD)
        self.listing = make_listing(self.owner)

    def toggle(self, user, body=None):
        return client_for(user).patch(detail(self.listing, 'toggle-status/'), body, format='json')

    def test_toggle_without_body_flips(self):
        self.assertFalse(self.toggle(self.owner).json()['is_active'])
        self.assertTrue(self.toggle(self.owner).json()['is_active'])

    def test_explicit_value_is_idempotent(self):
        self.assertFalse(self.toggle(self.owner, {'is_active': False}).json()['is_active'])
        self.assertFalse(self.toggle(self.owner, {'is_active': False}).json()['is_active'])  # повтор не включает обратно
        self.assertTrue(self.toggle(self.owner, {'is_active': True}).json()['is_active'])

    def test_invalid_value(self):
        self.assertEqual(self.toggle(self.owner, {'is_active': 'maybe'}).status_code, 400)

    def test_updated_at_changes(self):
        before = self.listing.updated_at
        self.toggle(self.owner)
        self.listing.refresh_from_db()
        self.assertGreater(self.listing.updated_at, before)  # update_fields включает updated_at

    def test_only_owner_can_toggle(self):
        self.assertEqual(self.toggle(make_user('o2@example.com', Role.LANDLORD)).status_code, 403)
        self.assertEqual(self.toggle(make_user('t@example.com')).status_code, 403)
        self.assertEqual(APIClient().patch(detail(self.listing, 'toggle-status/')).status_code, 401)


class ListingSearchAndFilterTests(BaseAPITestCase):
    @classmethod
    def setUpTestData(cls):
        owner = make_user('owner@example.com', Role.LANDLORD)
        make_listing(owner, title='Cozy Balkon flat', description='Sunny place near the river',
                     city='Berlin', district='Mitte', price=Decimal('50'), rooms=1, housing_type='apartment')
        make_listing(owner, title='Big garden house', description='Quiet street with a balkon and garden',
                     city='Hamburg', district='Altona', price=Decimal('200'), rooms=5, housing_type='house')
        make_listing(owner, title='Studio near station', description='Compact and modern studio',
                     city='Berlin', district='Kreuzberg', price=Decimal('80'), rooms=2, housing_type='studio')
        make_listing(owner, title='Hidden Berlin flat', description='Should never be shown in lists',
                     city='Berlin', price=Decimal('60'), rooms=2, is_active=False)

    def get(self, query):
        return APIClient().get(f'{LISTINGS}?{query}')

    def test_only_active_listings(self):
        self.assertEqual(self.get('').json()['count'], 3)

    def test_search_in_title_and_description_case_insensitive(self):
        self.assertEqual(sorted(titles(self.get('search=BALKON'))), ['Big garden house', 'Cozy Balkon flat'])
        self.assertEqual(titles(self.get('search=river')), ['Cozy Balkon flat'])  # только в описании

    def test_all_search_words_must_match(self):
        self.assertEqual(titles(self.get('search=balkon garden')), ['Big garden house'])
        self.assertEqual(titles(self.get('search=balkon nonexistent')), [])

    def test_blank_search_means_no_search(self):
        self.assertEqual(self.get('search=').json()['count'], 3)

    def test_search_does_not_treat_wildcards_specially(self):
        self.assertEqual(self.get('search=%25').json()['count'], 0)  # '%' ищется буквально

    def test_city_is_case_insensitive_exact(self):
        self.assertEqual(self.get('city=berlin').json()['count'], 2)
        self.assertEqual(self.get('city=Berl').json()['count'], 0)  # iexact, а не icontains

    def test_district(self):
        self.assertEqual(titles(self.get('district=kreuzberg')), ['Studio near station'])

    def test_price_range_is_inclusive(self):
        self.assertEqual(sorted(titles(self.get('price_min=50&price_max=80'))), ['Cozy Balkon flat', 'Studio near station'])
        self.assertEqual(titles(self.get('price_min=100')), ['Big garden house'])
        self.assertEqual(self.get('price_max=49.99').json()['count'], 0)

    def test_rooms_range(self):
        self.assertEqual(sorted(titles(self.get('rooms_min=2&rooms_max=5'))), ['Big garden house', 'Studio near station'])
        self.assertEqual(titles(self.get('rooms_max=1')), ['Cozy Balkon flat'])

    def test_housing_type_single_and_multiple(self):
        self.assertEqual(titles(self.get('housing_type=house')), ['Big garden house'])
        self.assertEqual(sorted(titles(self.get('housing_type=house, Studio,house'))), ['Big garden house', 'Studio near station'])

    def test_combined_filters(self):
        self.assertEqual(titles(self.get('city=berlin&rooms_min=2&price_max=100')), ['Studio near station'])

    def test_invalid_parameters_return_400(self):
        bad = ['price_min=abc', 'price_max=x', 'price_min=-1', 'price_min=100&price_max=50', 'rooms_min=0',
               'rooms_max=51', 'rooms_min=abc', 'rooms_min=5&rooms_max=2', 'housing_type=castle',
               'housing_type=house,castle', 'ordering=password', 'ordering=--price', 'search=' + 'x' * 101]
        for query in bad:
            with self.subTest(query=query):
                response = self.get(query)
                self.assertEqual(response.status_code, 400)
                self.assertTrue(response.json())  # в теле — описание ошибки

    def test_error_names_the_field(self):
        self.assertIn('price_min', self.get('price_min=100&price_max=50').json())
        self.assertIn('housing_type', self.get('housing_type=castle').json())

    def test_ordering_by_price_and_default(self):
        self.assertEqual(titles(self.get('ordering=price')), ['Cozy Balkon flat', 'Studio near station', 'Big garden house'])
        self.assertEqual(titles(self.get('ordering=-price')), ['Big garden house', 'Studio near station', 'Cozy Balkon flat'])
        self.assertEqual(titles(self.get('')), ['Studio near station', 'Big garden house', 'Cozy Balkon flat'])  # новые первыми

    def test_ordering_by_created_at(self):
        self.assertEqual(titles(self.get('ordering=created_at')), ['Cozy Balkon flat', 'Big garden house', 'Studio near station'])
        self.assertEqual(titles(self.get('ordering=-created_at')), ['Studio near station', 'Big garden house', 'Cozy Balkon flat'])

    def test_pagination_keeps_filters(self):
        data = self.get('city=berlin&page_size=1&ordering=price').json()
        self.assertEqual((data['count'], len(data['results'])), (2, 1))
        self.assertIn('city=berlin', data['next'])


class ListingSortByPopularityTests(BaseAPITestCase):
    def setUp(self):
        owner = make_user('owner@example.com', Role.LANDLORD)
        self.a = make_listing(owner, title='Listing A')
        self.b = make_listing(owner, title='Listing B')
        self.c = make_listing(owner, title='Listing C no reviews')
        for _ in range(3):
            ListingView.objects.create(listing=self.a)
        ListingView.objects.create(listing=self.b)
        for i, (listing, rating) in enumerate([(self.a, 2), (self.b, 5), (self.b, 4)]):
            Review.objects.create(listing=listing, author=make_user(f'r{i}@example.com'), rating=rating, comment='ok')

    def order(self, ordering):
        return titles(APIClient().get(f'{LISTINGS}?ordering={ordering}'))

    def test_by_views(self):
        self.assertEqual(self.order('-views'), ['Listing A', 'Listing B', 'Listing C no reviews'])
        self.assertEqual(self.order('views')[0], 'Listing C no reviews')

    def test_by_reviews_count(self):
        self.assertEqual(self.order('-reviews')[:2], ['Listing B', 'Listing A'])

    def test_by_rating_puts_unrated_last_in_both_directions(self):
        # B: (5+4)/2 = 4.5, A: 2.0, C: нет отзывов -> NULL, всегда в конце.
        self.assertEqual(self.order('-rating'), ['Listing B', 'Listing A', 'Listing C no reviews'])
        self.assertEqual(self.order('rating'), ['Listing A', 'Listing B', 'Listing C no reviews'])

    def test_unrated_listing_has_null_rating_in_response(self):
        results = {x['title']: x for x in APIClient().get(LISTINGS).json()['results']}
        self.assertIsNone(results['Listing C no reviews']['avg_rating'])
        self.assertEqual(results['Listing B']['avg_rating'], 4.5)
        self.assertEqual((results['Listing A']['views_count'], results['Listing B']['reviews_count']), (3, 2))

    def test_popular_endpoint_orders_by_views_and_hides_inactive(self):
        owner = self.a.owner
        make_listing(owner, title='Hidden but very popular', is_active=False)
        hidden = Listing.objects.get(title='Hidden but very popular')
        for _ in range(10):
            ListingView.objects.create(listing=hidden)
        response = APIClient().get(f'{LISTINGS}popular/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(titles(response), ['Listing A', 'Listing B', 'Listing C no reviews'])


class ListingViewsHistoryTests(BaseAPITestCase):
    def setUp(self):
        self.owner = make_user('owner@example.com', Role.LANDLORD)
        self.tenant = make_user('tenant@example.com')
        self.listing = make_listing(self.owner)

    def test_anonymous_view_is_recorded_without_user(self):
        body = APIClient().get(detail(self.listing)).json()
        self.assertEqual(body['views_count'], 1)
        view = ListingView.objects.get()
        self.assertIsNone(view.user)

    def test_authenticated_view_is_recorded_with_user(self):
        client_for(self.tenant).get(detail(self.listing))
        self.assertEqual(ListingView.objects.get().user, self.tenant)

    def test_owner_views_are_not_counted(self):
        body = client_for(self.owner).get(detail(self.listing)).json()
        self.assertEqual(body['views_count'], 0)
        self.assertEqual(ListingView.objects.count(), 0)

    def test_every_view_counts(self):
        client = client_for(self.tenant)
        for _ in range(3):
            body = client.get(detail(self.listing)).json()
        self.assertEqual((body['views_count'], ListingView.objects.count()), (3, 3))

    def test_list_does_not_record_views(self):
        APIClient().get(LISTINGS)
        self.assertEqual(ListingView.objects.count(), 0)

    def test_404_does_not_record_views(self):
        hidden = make_listing(self.owner, is_active=False)
        APIClient().get(detail(hidden))
        self.assertEqual(ListingView.objects.count(), 0)


class MyListingsTests(BaseAPITestCase):
    def setUp(self):
        self.owner = make_user('owner@example.com', Role.LANDLORD)
        self.other = make_user('other@example.com', Role.LANDLORD)
        make_listing(self.owner, title='Mine active')
        make_listing(self.owner, title='Mine hidden', is_active=False)
        make_listing(self.other, title='Not mine')

    def test_includes_inactive_and_excludes_foreign(self):
        response = client_for(self.owner).get(f'{LISTINGS}my/')
        self.assertEqual(sorted(titles(response)), ['Mine active', 'Mine hidden'])

    def test_filters_apply_and_invalid_params_are_400(self):
        client = client_for(self.owner)
        self.assertEqual(titles(client.get(f'{LISTINGS}my/?search=hidden')), ['Mine hidden'])
        self.assertEqual(client.get(f'{LISTINGS}my/?price_min=abc').status_code, 400)

    def test_tenant_403_anonymous_401(self):
        self.assertEqual(client_for(make_user('t@example.com')).get(f'{LISTINGS}my/').status_code, 403)
        self.assertEqual(APIClient().get(f'{LISTINGS}my/').status_code, 401)


class SearchHistoryTests(BaseAPITestCase):
    def setUp(self):
        self.owner = make_user('owner@example.com', Role.LANDLORD)
        self.tenant = make_user('tenant@example.com')
        make_listing(self.owner, title='Cozy Balkon flat')

    def keywords(self, **filters):
        return list(SearchQuery.objects.filter(**filters).values_list('keyword', flat=True))

    def test_search_is_saved_normalized_with_user(self):
        client_for(self.tenant).get(f'{LISTINGS}?search=Cozy++BALKON')
        self.assertEqual(self.keywords(user=self.tenant), ['cozy balkon'])

    def test_anonymous_search_is_saved_without_user(self):
        APIClient().get(f'{LISTINGS}?search=berlin')
        self.assertEqual(self.keywords(user=None), ['berlin'])

    def test_search_is_saved_even_without_results(self):
        APIClient().get(f'{LISTINGS}?search=nothing-matches')
        self.assertEqual(self.keywords(), ['nothing-matches'])

    def test_requests_without_search_are_not_saved(self):
        APIClient().get(LISTINGS)
        APIClient().get(f'{LISTINGS}?search=&city=berlin')
        self.assertEqual(SearchQuery.objects.count(), 0)

    def test_invalid_requests_are_not_saved(self):
        APIClient().get(f'{LISTINGS}?search=berlin&price_min=abc')
        self.assertEqual(SearchQuery.objects.count(), 0)

    def test_next_pages_of_same_search_are_not_new_searches(self):
        client = APIClient()
        client.get(f'{LISTINGS}?search=flat')
        client.get(f'{LISTINGS}?search=flat&page=1')
        self.assertEqual(SearchQuery.objects.count(), 2)  # page=1 — тот же новый поиск
        client.get(f'{LISTINGS}?search=flat&page=2')
        self.assertEqual(SearchQuery.objects.count(), 2)  # page=2 не считается

    def test_my_history_is_private_and_newest_first(self):
        client_for(self.tenant).get(f'{LISTINGS}?search=first')
        client_for(self.tenant).get(f'{LISTINGS}?search=second')
        client_for(self.owner).get(f'{LISTINGS}?search=secret')
        response = client_for(self.tenant).get(f'{LISTINGS}searches/my/')
        self.assertEqual([x['keyword'] for x in response.json()['results']], ['second', 'first'])

    def test_my_history_requires_token(self):
        self.assertEqual(APIClient().get(f'{LISTINGS}searches/my/').status_code, 401)

    def test_popular_searches_group_and_order(self):
        for word, times in (('berlin', 3), ('hamburg', 1), ('munich', 2)):
            for _ in range(times):
                SearchQuery.objects.create(keyword=word)
        response = APIClient().get(f'{LISTINGS}searches/popular/')  # публично, без токена
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [{'keyword': 'berlin', 'count': 3}, {'keyword': 'munich', 'count': 2},
                                           {'keyword': 'hamburg', 'count': 1}])

    def test_popular_searches_limit(self):
        for i in range(5):
            SearchQuery.objects.create(keyword=f'word{i}')
        self.assertEqual(len(APIClient().get(f'{LISTINGS}searches/popular/?limit=2').json()), 2)
        self.assertEqual(len(APIClient().get(f'{LISTINGS}searches/popular/').json()), 5)

    def test_popular_searches_invalid_limit(self):
        for limit in ('0', '-1', 'abc', '101'):
            with self.subTest(limit=limit):
                self.assertEqual(APIClient().get(f'{LISTINGS}searches/popular/?limit={limit}').status_code, 400)

    def test_popular_searches_group_across_users(self):
        # Регрессия: без явного order_by сортировка модели (-created_at) попала бы в GROUP BY,
        # и каждый запрос считался бы отдельно (count всегда 1).
        SearchQuery.objects.create(keyword='berlin', user=self.tenant)
        SearchQuery.objects.create(keyword='berlin', user=self.owner)
        SearchQuery.objects.create(keyword='berlin')
        self.assertEqual(APIClient().get(f'{LISTINGS}searches/popular/').json(), [{'keyword': 'berlin', 'count': 3}])
