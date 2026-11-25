from django.contrib import admin

from apps.reviews.models import Review


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ('listing', 'author', 'rating', 'created_at')
    list_filter = ('rating',)
    raw_id_fields = ('listing', 'author', 'booking')
    list_select_related = ('listing', 'author')
