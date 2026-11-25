from django.contrib import admin

from apps.listings.models import Listing, ListingView, SearchQuery


@admin.register(Listing)
class ListingAdmin(admin.ModelAdmin):
    list_display = ('title', 'city', 'price', 'rooms', 'housing_type', 'is_active', 'owner')
    list_filter = ('is_active', 'housing_type', 'city')
    search_fields = ('title', 'description', 'city', 'district', 'address')
    list_select_related = ('owner',)  # одним JOIN-ом, а не по запросу на каждую строку (N+1)
    raw_id_fields = ('owner',)        # поле-поиск вместо выпадающего списка на всех пользователей


@admin.register(ListingView)
class ListingViewAdmin(admin.ModelAdmin):
    list_display = ('listing', 'user', 'viewed_at')
    raw_id_fields = ('listing', 'user')
    list_select_related = ('listing', 'user')


@admin.register(SearchQuery)
class SearchQueryAdmin(admin.ModelAdmin):
    list_display = ('keyword', 'user', 'created_at')
    search_fields = ('keyword',)
    raw_id_fields = ('user',)
