from django.contrib import admin

from apps.bookings.models import Booking


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ('listing', 'tenant', 'start_date', 'end_date', 'total_price', 'status')
    list_filter = ('status',)
    raw_id_fields = ('listing', 'tenant')
    list_select_related = ('listing', 'tenant')
