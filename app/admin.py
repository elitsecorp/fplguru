from django.contrib import admin
from .models import FlightPlan


@admin.register(FlightPlan)
class FlightPlanAdmin(admin.ModelAdmin):
    list_display = ('callsign', 'time_departure', 'time_arrival', 'takeoff_weight')
    search_fields = ('callsign',)
    readonly_fields = ('created_at', 'updated_at')
