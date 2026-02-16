import math
from datetime import datetime, timezone
from pathlib import Path
import yaml


def load_thresholds(path=None):
    # Deterministic load of thresholds from YAML; if missing, use sane defaults.
    default = {
        'crosswind_limit_kt': 20,
        'wind_speed_threshold_kt': 30,
        'icing_temp_c': 0,
        'min_rvr_m': 550,
        'min_cloud_base_ft': 200,
        'max_flight_level': 450,
        'data_quality': {
            'required_fields': ['callsign', 'time_departure', 'time_arrival'],
            'ambiguous_time_tolerance_minutes': 5,
        }
    }
    if not path:
        return default
    p = Path(path)
    if not p.exists():
        return default
    try:
        with p.open('r', encoding='utf-8') as f:
            loaded = yaml.safe_load(f)
            if not isinstance(loaded, dict):
                return default
            # merge defaults for any missing keys
            merged = default.copy()
            merged.update(loaded)
            return merged
    except Exception:
        return default


def compute_crosswind(wind_dir_deg, runway_heading_deg, wind_speed_kt):
    # Deterministic crosswind calculation (absolute value)
    angle = abs((wind_dir_deg - runway_heading_deg + 180) % 360 - 180)
    return abs(math.sin(math.radians(angle))) * wind_speed_kt


def validate_flightplan(fpl: dict, thresholds: dict):
    """
    Validate presence/format of key flightplan fields. Returns a data_quality dict with 'missing' and 'ambiguous'.
    This function never mutates the input and is deterministic.
    """
    data_quality = {'missing': [], 'ambiguous': []}
    required = thresholds.get('data_quality', {}).get('required_fields', [])
    for field in required:
        if fpl.get(field) in (None, '', []):
            data_quality['missing'].append(field)

    # Check numeric fields are numbers
    numeric_fields = ['takeoff_weight', 'landing_weight', 'zerofuel_weight', 'ground_distance',
                      'trip_fuel', 'contingency', 'minimum_takeoff_fuel', 'corrected_minimum_takeoff_fuel']
    for nf in numeric_fields:
        val = fpl.get(nf)
        if val is None:
            data_quality['missing'].append(nf)
        else:
            try:
                float(val)
            except Exception:
                data_quality['ambiguous'].append(nf)

    # Check weather structure for required subfields at takeoff and destination
    weather = fpl.get('weather') or {}
    for section in ('takeoff', 'destination'):
        sec = weather.get(section) if isinstance(weather, dict) else None
        if not sec:
            data_quality['missing'].append(f'weather.{section}')
        else:
            for req in ('wind_dir_deg', 'wind_speed_kt', 'temperature_c'):
                if sec.get(req) is None:
                    data_quality['missing'].append(f'weather.{section}.{req}')

    # Remove duplicates and sort
    data_quality['missing'] = sorted(set(data_quality['missing']))
    data_quality['ambiguous'] = sorted(set(data_quality['ambiguous']))
    return data_quality


def analyze_flightplan(fpl: dict, observations: list, thresholds: dict):
    """
    Analyze a flightplan dict and return flags, data_quality, evidence and timestamp.
    The function is pure and deterministic given inputs and thresholds.
    """
    flags = []

    data_quality = validate_flightplan(fpl, thresholds)

    # Example rule: crosswind at takeoff if runway_heading provided and takeoff wind present
    weather = fpl.get('weather') or {}
    takeoff_wx = weather.get('takeoff') if isinstance(weather, dict) else None
    runway_heading = fpl.get('runway_heading')  # optional field; degrees

    if takeoff_wx and runway_heading is not None and not data_quality['missing']:
        wind_dir = takeoff_wx.get('wind_dir_deg')
        wind_speed = takeoff_wx.get('wind_speed_kt')
        cw = compute_crosswind(float(wind_dir), float(runway_heading), float(wind_speed))
        limit = float(thresholds.get('crosswind_limit_kt', 20))
        if cw >= limit:
            flags.append({
                'code': 'CROSSWIND',
                'severity': 'HIGH',
                'reason': f'Crosswind {cw:.1f} kt >= limit {limit} kt',
                'details': {
                    'crosswind_kt': round(cw, 1),
                    'threshold_kt': limit,
                    'wind_dir_deg': wind_dir,
                    'wind_speed_kt': wind_speed,
                    'runway_heading_deg': runway_heading,
                }
            })
    else:
        # If takeoff weather or runway not provided, mark the rule as undetermined
        if not takeoff_wx:
            if 'weather.takeoff' not in data_quality['missing']:
                data_quality['missing'].append('weather.takeoff')
        if runway_heading is None:
            if 'runway_heading' not in data_quality['missing']:
                data_quality['missing'].append('runway_heading')

    # Always include evidence: provided observations + key fields
    evidence = {
        'flightplan_snapshot': {k: v for k, v in fpl.items() if k in ['callsign', 'time_departure', 'time_arrival', 'route_text']},
        'provided_weather': takeoff_wx,
        'observations_count': len(observations),
    }

    result = {
        'flags': flags,
        'data_quality': data_quality,
        'evidence': evidence,
        'timestamp_utc': datetime.now(timezone.utc).isoformat(),
    }
    return result
