from django.urls import path

from apps.bookings import views

# Конкретные пути (requests/) идут раньше <uuid:pk>/.
urlpatterns = [
    path('', views.BookingListCreateView.as_view(), name='booking-list'),
    path('requests/', views.BookingRequestsView.as_view(), name='booking-requests'),
    path('<uuid:pk>/', views.BookingDetailView.as_view(), name='booking-detail'),
    path('<uuid:pk>/cancel/', views.BookingCancelView.as_view(), name='booking-cancel'),
    path('<uuid:pk>/confirm/', views.BookingConfirmView.as_view(), name='booking-confirm'),
    path('<uuid:pk>/reject/', views.BookingRejectView.as_view(), name='booking-reject'),
]
