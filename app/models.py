from django.db import models
from django.utils import timezone


class FlightPlan(models.Model):
    """
    FlightPlan schema for FPL Guru.

    Notes on units (explicit):
    - Weights: kilograms (kg)
    - Distances: nautical miles (NM)
    - Fuel quantities: kilograms (kg)
    - Times: stored in UTC as DateTimeField

    Weather fields are stored in a structured JSON object with the following top-level keys:
    - takeoff, enroute, etops, destination, destination_alternates
    Each of those keys should contain an object describing observed/forecast conditions, for example:
      {
        "wind_dir_deg": 270,
        "wind_speed_kt": 18,
        "visibility_m": 8000,
        "rvr_m": 1200,
        "cloud_base_ft": 200,
        "temperature_c": 3,
        "remarks": ""
      }

    ETOPS alternates and destination_alternate may be a single ICAO string or a list; stored as JSON to support both.
    Company/area NOTAMs are free text stored in `company_area_notams`.
    """

    # Identifying fields
    callsign = models.CharField(max_length=16, blank=True, null=True, help_text="Callsign / flight ID")

    # Timing (UTC)
    time_departure = models.DateTimeField(help_text="Planned departure time (UTC)")
    time_arrival = models.DateTimeField(help_text="Planned arrival time (UTC)")

    # Weights (kg)
    takeoff_weight = models.DecimalField(max_digits=10, decimal_places=2, help_text="Takeoff weight (kg)")
    landing_weight = models.DecimalField(max_digits=10, decimal_places=2, help_text="Estimated landing weight (kg)")
    zerofuel_weight = models.DecimalField(max_digits=10, decimal_places=2, help_text="Zero fuel weight (kg)")

    # Distances
    ground_distance = models.DecimalField(max_digits=10, decimal_places=2, help_text="Ground distance (NM)")

    # Fuel figures (kg)
    trip_fuel = models.DecimalField(max_digits=10, decimal_places=2, help_text="Trip fuel (kg)")
    contingency = models.DecimalField(max_digits=10, decimal_places=2, help_text="Contingency fuel (kg)")
    minimum_takeoff_fuel = models.DecimalField(max_digits=10, decimal_places=2, help_text="Minimum takeoff fuel (kg)")
    corrected_minimum_takeoff_fuel = models.DecimalField(max_digits=10, decimal_places=2, help_text="Corrected minimum takeoff fuel (kg)")

    # Alternates and ETOPS
    destination_alternate = models.JSONField(blank=True, null=True, help_text="Destination alternate(s). ICAO string or list of ICAO strings")
    is_etops = models.BooleanField(default=False, help_text="Indicates this flight is ETOPS")
    etops_alternates = models.JSONField(blank=True, null=True, help_text="List of ETOPS alternates (ICAO codes)")

    # Weather (structured JSON for each stage)
    # keys: takeoff, enroute, etops, destination, destination_alternates
    weather = models.JSONField(blank=True, null=True, help_text="Structured weather object with keys: takeoff, enroute, etops, destination, destination_alternates")

    # Company / area NOTAMs
    company_area_notams = models.TextField(blank=True, help_text="Company or area NOTAMs relevant to the flight plan")

    # Administrative
    route_text = models.TextField(blank=True, help_text="Route text / clearance route")
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Flight Plan"
        verbose_name_plural = "Flight Plans"
        indexes = [
            models.Index(fields=["callsign"]),
            models.Index(fields=["time_departure"]),
            models.Index(fields=["time_arrival"]),
        ]

    def __str__(self):
        cs = self.callsign if self.callsign else "<unknown>"
        return f"FlightPlan {cs} {self.time_departure.isoformat()} -> {self.time_arrival.isoformat()}"
