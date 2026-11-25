from django.db import IntegrityError, transaction
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
from apps.listings.models import Listing
from apps.reviews.models import Review
from apps.users.choices.roles import Role

GOOD = {'rating': 5, 'comment': 'Wonderful flat, very clean and quiet.'}


def reviews_url(listing):
    return f'{API}listings/{listing.pk}/reviews/'


class ReviewTestBase(BaseAPITestCase):
    def setUp(self):
        self.landlord = make_user('landlord@example.com', Role.LANDLORD)
        self.guest = make_user('guest@example.com')      # жил: завершённая подтверждённая бронь
        self.guest2 = make_user('guest2@example.com')
        self.stranger = make_user('stranger@example.com')  # броней нет
        self.listing = make_listing(self.landlord)
        self.stay = make_booking(self.listing, self.guest, -10, -7, BookingStatus.CONFIRMED)

    def post(self, user, body=None, listing=None):
        return client_for(user).post(reviews_url(listing or self.listing), body or GOOD, format='json')


class ReviewCreateTests(ReviewTestBase):
    def test_tenant_with_completed_stay_can_review(self):
        response = self.post(self.guest)
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual((body['rating'], body['comment']), (5, GOOD['comment']))
        self.assertEqual((body['listing'], body['author']['id']), (str(self.listing.pk), str(self.guest.pk)))
        self.assertNotIn('email', body['author'])

    def test_review_is_linked_to_the_completed_booking(self):
        review = Review.objects.get(pk=self.post(self.guest).json()['id'])
        self.assertEqual(review.booking, self.stay)

    def test_body_cannot_set_author_or_listing(self):
        other_listing = make_listing(self.landlord, title='Other listing')
        response = self.post(self.guest, {**GOOD, 'author': str(self.guest2.pk), 'listing': str(other_listing.pk)})
        self.assertEqual(response.status_code, 201)
        review = Review.objects.get()
        self.assertEqual((review.author, review.listing), (self.guest, self.listing))

    def test_stay_ending_today_counts_as_completed(self):
        make_booking(make_listing(self.landlord, title='Ends today'), self.guest2, -3, 0, BookingStatus.CONFIRMED)
        listing = Listing.objects.get(title='Ends today')
        self.assertEqual(self.post(self.guest2, listing=listing).status_code, 201)

    def test_roles_and_authentication(self):
        self.assertEqual(self.post(self.landlord).status_code, 403)
        self.assertEqual(APIClient().post(reviews_url(self.listing), GOOD, format='json').status_code, 401)

    def test_no_booking_means_no_review(self):
        self.assertEqual(self.post(self.stranger).status_code, 403)

    def test_only_a_completed_confirmed_booking_qualifies(self):
        cases = {
            'future confirmed': (5, 8, BookingStatus.CONFIRMED),
            'ongoing confirmed': (-2, 3, BookingStatus.CONFIRMED),
            'past pending': (-10, -7, BookingStatus.PENDING),
            'past cancelled': (-10, -7, BookingStatus.CANCELLED),
            'past rejected': (-10, -7, BookingStatus.REJECTED),
        }
        for label, (start, end, status_) in cases.items():
            with self.subTest(label):
                user = make_user(f'{label.replace(" ", "")}@example.com')
                make_booking(self.listing, user, start, end, status_)
                self.assertEqual(self.post(user).status_code, 403)
        self.assertEqual(Review.objects.count(), 0)

    def test_completed_stay_on_another_listing_is_not_enough(self):
        other = make_listing(self.landlord, title='Another one')
        user = make_user('elsewhere@example.com')
        make_booking(other, user, -10, -7, BookingStatus.CONFIRMED)
        self.assertEqual(self.post(user).status_code, 403)       # на нашем объявлении не жил
        self.assertEqual(self.post(user, listing=other).status_code, 201)

    def test_one_review_per_listing(self):
        self.assertEqual(self.post(self.guest).status_code, 201)
        response = self.post(self.guest, {'rating': 1, 'comment': 'second attempt'})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(Review.objects.count(), 1)

    def test_same_author_can_review_different_listings(self):
        other = make_listing(self.landlord, title='Another one')
        make_booking(other, self.guest, -10, -7, BookingStatus.CONFIRMED)
        self.assertEqual(self.post(self.guest).status_code, 201)
        self.assertEqual(self.post(self.guest, listing=other).status_code, 201)

    def test_database_enforces_uniqueness_and_rating_range(self):
        Review.objects.create(listing=self.listing, author=self.guest, rating=4, comment='ok')
        with self.assertRaises(IntegrityError), transaction.atomic():
            Review.objects.create(listing=self.listing, author=self.guest, rating=3, comment='dup')
        with self.assertRaises(IntegrityError), transaction.atomic():
            Review.objects.create(listing=self.listing, author=self.guest2, rating=9, comment='bad rating')

    def test_validation(self):
        bad = {
            'rating 0': {'rating': 0, 'comment': 'fine text'},
            'rating 6': {'rating': 6, 'comment': 'fine text'},
            'rating text': {'rating': 'abc', 'comment': 'fine text'},
            'rating float': {'rating': 4.5, 'comment': 'fine text'},
            'empty comment': {'rating': 4, 'comment': ''},
            'blank comment': {'rating': 4, 'comment': '   '},
            'missing rating': {'comment': 'fine text'},
            'missing comment': {'rating': 4},
            'comment too long': {'rating': 4, 'comment': 'x' * 2001},
        }
        for label, body in bad.items():
            with self.subTest(label):
                self.assertEqual(self.post(self.guest, body).status_code, 400)
        self.assertEqual(Review.objects.count(), 0)

    def test_rating_boundaries_are_accepted(self):
        make_booking(self.listing, self.guest2, -20, -17, BookingStatus.CONFIRMED)
        for rating, user in ((1, self.guest), (5, self.guest2)):
            with self.subTest(rating=rating):
                self.assertEqual(self.post(user, {'rating': rating, 'comment': 'boundary'}).status_code, 201)

    def test_unknown_and_hidden_listing(self):
        unknown = f'{API}listings/019a0000-0000-7000-8000-000000000000/reviews/'
        self.assertEqual(client_for(self.guest).post(unknown, GOOD, format='json').status_code, 404)
        self.listing.is_active = False
        self.listing.save()
        self.assertEqual(self.post(self.guest).status_code, 404)


class ReviewListTests(ReviewTestBase):
    def test_public_read_without_token(self):
        response = APIClient().get(reviews_url(self.listing))
        self.assertEqual((response.status_code, response.json()['count']), (200, 0))

    def test_list_shows_reviews_newest_first_with_author_name(self):
        Review.objects.create(listing=self.listing, author=self.guest, rating=5, comment='first')
        Review.objects.create(listing=self.listing, author=self.guest2, rating=2, comment='second')
        results = APIClient().get(reviews_url(self.listing)).json()['results']
        self.assertEqual([x['comment'] for x in results], ['second', 'first'])
        self.assertEqual(results[0]['author']['first_name'], 'Test')
        self.assertNotIn('email', results[0]['author'])

    def test_only_reviews_of_this_listing(self):
        other = make_listing(self.landlord, title='Another one')
        Review.objects.create(listing=other, author=self.guest, rating=1, comment='elsewhere')
        self.assertEqual(APIClient().get(reviews_url(self.listing)).json()['count'], 0)
        self.assertEqual(APIClient().get(reviews_url(other)).json()['count'], 1)

    def test_pagination(self):
        for i in range(3):
            Review.objects.create(listing=self.listing, author=make_user(f'u{i}@example.com'), rating=3, comment=f'c{i}')
        data = APIClient().get(reviews_url(self.listing) + '?page_size=2').json()
        self.assertEqual((data['count'], len(data['results']), bool(data['next'])), (3, 2, True))

    def test_unknown_listing_is_404(self):
        self.assertEqual(APIClient().get(f'{API}listings/019a0000-0000-7000-8000-000000000000/reviews/').status_code, 404)

    def test_hidden_listing_reviews_visible_only_to_owner(self):
        self.listing.is_active = False
        self.listing.save()
        self.assertEqual(APIClient().get(reviews_url(self.listing)).status_code, 404)
        self.assertEqual(client_for(self.guest).get(reviews_url(self.listing)).status_code, 404)
        self.assertEqual(client_for(self.landlord).get(reviews_url(self.listing)).status_code, 200)


class RatingOnListingTests(ReviewTestBase):
    def listing_body(self):
        return APIClient().get(f'{API}listings/{self.listing.pk}/').json()

    def test_rating_is_null_until_first_review(self):
        body = self.listing_body()
        self.assertEqual((body['reviews_count'], body['avg_rating']), (0, None))

    def test_rating_updates_after_each_review(self):
        self.post(self.guest, {'rating': 5, 'comment': 'great'})
        body = self.listing_body()
        self.assertEqual((body['reviews_count'], body['avg_rating']), (1, 5.0))
        make_booking(self.listing, self.guest2, -20, -17, BookingStatus.CONFIRMED)
        self.post(self.guest2, {'rating': 2, 'comment': 'noisy'})
        body = self.listing_body()
        self.assertEqual((body['reviews_count'], body['avg_rating']), (2, 3.5))
