from django.urls import path

from apps.listings import views

# Порядок важен: конкретные пути (my/, popular/, searches/...) идут РАНЬШЕ <uuid:pk>/.
# Для uuid-конвертера слово «my» всё равно не подошло бы, но так порядок читается однозначно.
urlpatterns = [
    path('', views.ListingListCreateView.as_view(), name='listing-list'),
    path('my/', views.MyListingsView.as_view(), name='listing-my'),
    path('popular/', views.PopularListingsView.as_view(), name='listing-popular'),
    path('searches/popular/', views.PopularSearchesView.as_view(), name='search-popular'),
    path('searches/my/', views.MySearchesView.as_view(), name='search-my'),
    path('<uuid:pk>/', views.ListingDetailView.as_view(), name='listing-detail'),
    path('<uuid:pk>/toggle-status/', views.ListingToggleStatusView.as_view(), name='listing-toggle'),
]
