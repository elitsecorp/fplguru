import os
import requests
from typing import Dict, Any
import json
import re

DEESEEK_API_URL = 'https://api.deepseek.com/chat/completions'
DEESEEK_API_KEY_ENV = 'FPL_DEEPSEEK_API_KEY'


def _get_api_key():
    key = 'sk-8e7f84702cc741429afa915c73998d97'
    if not key:
        raise RuntimeError(f"Deepseek API key not set. Set environment variable {DEESEEK_API_KEY_ENV}")
    return key


def extract_flightplan_from_text(text: str, schema: Dict[str, Any] = None, timeout: int = 20) -> Dict[str, Any]:
    """
    Send deterministic extraction request to Deepseek (or compatible) API. The function expects the
    remote service to return JSON matching the requested schema. This wrapper enforces that the API key
    is read from environment variables and does not hard-code secrets.

    Returns dict with keys: 'flightplan', 'data_quality', 'raw_llm_response'.
    """
    try:
        api_key = _get_api_key()
    except Exception as e:
        # Return a deterministic-shaped response with an llm_error for debugging
        # Define a detailed weather template so the flightplan always contains the expected nested structure
        weather_template = {
            seg: {
                'wind_speed': None,
                'wind_direction': None,
                'qnh': None,
                'visibility': None,
                'highest_cloud_coverage': None,
                'highest_cloud_type': None,
            } for seg in ['takeoff', 'enroute', 'etops', 'destination']
        }
        keys = ['callsign', 'time_departure', 'time_arrival', 'takeoff_weight', 'landing_weight', 'zerofuel_weight',
                'ground_distance', 'trip_fuel', 'contingency', 'minimum_takeoff_fuel', 'corrected_minimum_takeoff_fuel',
                'destination_alternate', 'is_etops', 'etops_alternates', 'weather', 'company_area_notams', 'route_text', 'runway_heading']
        flightplan = {k: None for k in keys}
        flightplan['weather'] = weather_template
        return {
            'flightplan': flightplan,
            'data_quality': {'missing': sorted(keys), 'ambiguous': []},
            'raw_llm_response': None,
            'raw_llm_response_text': None,
            'extracted_text': None,
            'llm_error': str(e),
        }
###
    # Build chat-style payload compatible with Deepseek chat completions
    system_prompt = (
        'You are a deterministic extractor. Extract ONLY a JSON object matching the schema described by the user. '
        'Do not add any commentary or explanations. Return strictly valid JSON.'
    )
    # Truncate very large texts to avoid request size errors (keep head of document where headers live)
    max_text_len = 30000
    send_text = text if len(text) <= max_text_len else text[:max_text_len] + '\n\n...[TRUNCATED]...'

    user_instructions = (
        "Given the following flight plan text, extract flight plan fields into JSON with keys: "
        "callsign, time_departure, time_arrival, takeoff_weight, landing_weight, zerofuel_weight, ground_distance, "
        "trip_fuel, contingency, minimum_takeoff_fuel, corrected_minimum_takeoff_fuel, destination_alternate, is_etops, "
        "etops_alternates, weather, company_notams, area_notams, company_area_notams, "
        "route_text, runway_heading.\n\n"
        "The weather key must be an object with the following sub-objects: takeoff, enroute, etops, destination. "
        "Each of those must be an object containing the fields: "
        "wind_speed (numeric, knots), wind_direction (numeric, degrees true), qnh (numeric, hPa), visibility (numeric, meters or kilometers), "
        "highest_cloud_coverage (string, e.g. 'FEW','SCT','BKN','OVC'), highest_cloud_type (string, e.g. 'CB','TCU', or null). "
        "If a value cannot be determined set it to null. Use numeric types for numbers when possible. "
        "Return a top-level JSON object: {\"flightplan\": { ... }, \"data_quality\": {\"missing\": [...], \"ambiguous\": [...]}}. "
        "Only return JSON. Here is the text to parse:\n\n" + send_text
    )

    payload = {
        'model': 'deepseek-chat',
        'messages': [
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': user_instructions}
        ],
        'stream': False,
    }

    # DEBUG: Log payload sent to LLM (do not log API keys)
    try:
        preview = user_instructions if len(user_instructions) <= 20000 else user_instructions[:20000] + '\n...[TRUNCATED]...'
        print(f'LLM extract_flightplan_from_text payload lengths: send_text={len(send_text) if "send_text" in locals() and send_text else 0}, user_instructions={len(user_instructions)}')
        print('LLM extract_flightplan_from_text preview:\n', preview)
    except Exception:
        pass

    headers = {
        'Authorization': f'Bearer {api_key}',
        'Content-Type': 'application/json',
        'User-Agent': 'fplguru/1.0'
    }

    try:
        resp = requests.post(DEESEEK_API_URL, json=payload, headers=headers, timeout=timeout)
        resp.raise_for_status()
        resp_json = resp.json()
        # Extract assistant content
        assistant_text = None
        try:
            assistant_text = resp_json['choices'][0]['message']['content']
        except Exception:
            # Fallback shapes
            try:
                assistant_text = resp_json['choices'][0].get('text')
            except Exception:
                assistant_text = None
        if not assistant_text:
            raise RuntimeError('empty assistant content in LLM response')
        # Try to parse JSON returned by assistant
        try:
            llm_json = json.loads(assistant_text)
        except Exception as e_parse:
            # return debug info with raw assistant text
            weather_template = {
                seg: {
                    'wind_speed': None,
                    'wind_direction': None,
                    'qnh': None,
                    'visibility': None,
                    'highest_cloud_coverage': None,
                    'highest_cloud_type': None,
                } for seg in ['takeoff', 'enroute', 'etops', 'destination']
            }
            keys = ['callsign', 'time_departure', 'time_arrival', 'takeoff_weight', 'landing_weight', 'zerofuel_weight',
                    'ground_distance', 'trip_fuel', 'contingency', 'minimum_takeoff_fuel', 'corrected_minimum_takeoff_fuel',
                    'destination_alternate', 'is_etops', 'etops_alternates', 'weather', 'company_area_notams', 'route_text', 'runway_heading']
            flightplan = {k: None for k in keys}
            flightplan['weather'] = weather_template
            return {
                'flightplan': flightplan,
                'data_quality': {'missing': sorted(keys), 'ambiguous': []},
                'raw_llm_response': None,
                'raw_llm_response_text': assistant_text[:20000] if assistant_text else None,
                'extracted_text': assistant_text[:20000] if assistant_text else None,
                'llm_error': f'failed to parse JSON from assistant: {str(e_parse)}',
            }
    except requests.exceptions.RequestException as e:
        # Capture response text if available (truncate for safety)
        resp_text = None
        if hasattr(e, 'response') and e.response is not None:
            try:
                resp_text = e.response.text[:2000]
            except Exception:
                resp_text = None
        weather_template = {
            seg: {
                'wind_speed': None,
                'wind_direction': None,
                'qnh': None,
                'visibility': None,
                'highest_cloud_coverage': None,
                'highest_cloud_type': None,
            } for seg in ['takeoff', 'enroute', 'etops', 'destination']
        }
        keys = ['callsign', 'time_departure', 'time_arrival', 'takeoff_weight', 'landing_weight', 'zerofuel_weight',
                'ground_distance', 'trip_fuel', 'contingency', 'minimum_takeoff_fuel', 'corrected_minimum_takeoff_fuel',
                'destination_alternate', 'is_etops', 'etops_alternates', 'weather', 'company_area_notams', 'route_text', 'runway_heading']
        flightplan = {k: None for k in keys}
        flightplan['weather'] = weather_template
        return {
            'flightplan': flightplan,
            'data_quality': {'missing': sorted(keys), 'ambiguous': []},
            'raw_llm_response': None,
            'raw_llm_response_text': resp_text,
            'extracted_text': resp_text,
            'llm_error': str(e),
        }

    # Post-process to ensure deterministic shape and flag missing fields
    flightplan = llm_json.get('flightplan') if isinstance(llm_json, dict) else None
    if not isinstance(flightplan, dict):
        flightplan = {}

    # Ensure keys exist
    weather_template = {
        seg: {
            'wind_speed': None,
            'wind_direction': None,
            'qnh': None,
            'visibility': None,
            'highest_cloud_coverage': None,
            'highest_cloud_type': None,
        } for seg in ['takeoff', 'enroute', 'etops', 'destination']
    }
    keys = ['callsign', 'time_departure', 'time_arrival', 'takeoff_weight', 'landing_weight', 'zerofuel_weight',
            'ground_distance', 'trip_fuel', 'contingency', 'minimum_takeoff_fuel', 'corrected_minimum_takeoff_fuel',
            'destination_alternate', 'is_etops', 'etops_alternates', 'weather', 'company_area_notams', 'route_text', 'runway_heading']
    for k in keys:
        flightplan.setdefault(k, None)
    # Ensure nested weather structure exists
    if not isinstance(flightplan.get('weather'), dict):
        flightplan['weather'] = weather_template
    else:
        # fill any missing weather segments or keys
        for seg, seg_template in weather_template.items():
            seg_val = flightplan['weather'].get(seg)
            if not isinstance(seg_val, dict):
                flightplan['weather'][seg] = seg_template
            else:
                for fk in seg_template.keys():
                    seg_val.setdefault(fk, None)

    missing = [k for k, v in flightplan.items() if v in (None, '', [])]

    return {
        'flightplan': flightplan,
        'data_quality': {'missing': sorted(missing), 'ambiguous': []},
        'raw_llm_response': llm_json,
        'raw_llm_response_text': assistant_text[:20000] if 'assistant_text' in locals() and assistant_text else None,
        'extracted_text': assistant_text[:20000] if 'assistant_text' in locals() and assistant_text else None,
    }


def analyze_section(section: str, data: Dict[str, Any], timeout: int = 15) -> Dict[str, Any]:
    """
    Analyze a section of the minimal flightplan schema.

    - For 'weather' and 'notams' the function returns a multi-part analysis with a 'by_part' mapping, e.g.:
      {
        'section': 'weather',
        'by_part': {
          'departure': {'risk_level': 'low', 'flags': [], 'details': '...'},
          'enroute': {...},
          'destination': {...},
          'destination_alternate': {...}
        },
        'raw_llm_response_text': '...'
      }

    - For other sections it preserves the legacy single-section return with keys: section, risk_level, flags, details, raw_llm_response_text, llm_error (optional).
    """
    # Debug: print the raw `data` received by this function before any normalization
    try:
        received_preview = json.dumps(data) if isinstance(data, (dict, list)) else str(data)
        if len(received_preview) > 2000:
            received_preview = received_preview[:2000] + '\n...[TRUNCATED]...'
        print('LLM analyze_section RECEIVED data preview:', received_preview)
    except Exception:
        pass

    # Local helper to expand common NOTAM abbreviations
    def _expand_abbrevs_local(s: str) -> str:
        if not s:
            return s
        replacements = {
            r'\bSHRA\b': 'showers and rain',
            r'\bTS\b': 'thunderstorms',
            r'\bRVR\b': 'runway visual range',
            r'\bRWY\b': 'runway',
            r'\bICE\b': 'ice',
            r'\bSN\b': 'snow',
            r'\bDZ\b': 'drizzle',
            r'\bFG\b': 'fog',
            r'\bBKN\b': 'broken clouds',
            r'\bSCT\b': 'scattered clouds',
        }
        out = s
        for pat, rep in replacements.items():
            out = re.sub(pat, rep, out, flags=re.IGNORECASE)
        return out

    # If a full parse result was passed in, extract the minimal flightplan
    if isinstance(data, dict) and 'flightplan' in data and isinstance(data['flightplan'], dict):
        data = data['flightplan']

    # If caller passed the minimal parser result (from parse_pdf_file), it already follows the minimal schema
    # Normalize notams if necessary (support legacy shapes)
    if section == 'notams':
        notams = data.get('notams') if isinstance(data.get('notams'), dict) else None
        if notams:
            # Already normalized shape
            data = {'notams': notams}
        else:
            # attempt to build from legacy fields
            departure = data.get('departure') or None
            destination = data.get('destination') or None
            airport_notams = data.get('airport_notams') or {}
            if not airport_notams and isinstance(data.get('notams_by_airport'), dict):
                airport_notams = {k: v.get('entries') if isinstance(v, dict) and 'entries' in v else v for k, v in data.get('notams_by_airport', {}).items()}
            notams = {'departure': {}, 'destination': {}, 'enroute_alternates': {}, 'etops_alternates': {}, 'company': [], 'area': []}
            etops_list = data.get('etops_alternates') or []
            for icao, entries in (airport_notams or {}).items():
                if not entries:
                    continue
                cleaned = []
                if isinstance(entries, list):
                    for e in entries:
                        if not isinstance(e, str):
                            continue
                        cleaned.append(re.sub(r'\s+', ' ', _expand_abbrevs_local(e)).strip())
                else:
                    cleaned = [re.sub(r'\s+', ' ', _expand_abbrevs_local(str(entries))).strip()]
                if icao == departure:
                    notams['departure'][icao] = cleaned
                elif icao == destination:
                    notams['destination'][icao] = cleaned
                elif icao in etops_list:
                    notams['etops_alternates'][icao] = cleaned
                else:
                    notams['enroute_alternates'][icao] = cleaned
            if data.get('company_notams'):
                notams['company'] = [re.sub(r'\s+', ' ', _expand_abbrevs_local(p)).strip() for p in re.split(r'\n\s*\n', data['company_notams']) if p.strip()]
            if data.get('area_notams'):
                notams['area'] = [re.sub(r'\s+', ' ', _expand_abbrevs_local(p)).strip() for p in re.split(r'\n\s*\n', data['area_notams']) if p.strip()]
            data = {'notams': notams}

    # Normalize weather input if asked
    if section == 'weather':
        # Expect minimal schema where 'weather' is mapping ICAO -> {takeoff/enroute/destination/etops}
        weather_map = data.get('weather') if isinstance(data.get('weather'), dict) else {}
        # attempt to discover departure/destination icom from available context
        departure_icao = data.get('departure') or None
        destination_icao = data.get('destination') or None
        # fallback heuristics: if only 1 ICAO present consider it departure, if 2 present map first->dep second->dest
        icaos = [k for k in weather_map.keys() if re.match(r'^[A-Z]{4}$', k)]
        if not departure_icao and len(icaos) >= 1:
            departure_icao = icaos[0]
        if not destination_icao and len(icaos) >= 2:
            destination_icao = icaos[1]
        # Build payload parts
        departure_block = weather_map.get(departure_icao) if departure_icao else None
        destination_block = weather_map.get(destination_icao) if destination_icao else None
        enroute_block = {k: v for k, v in weather_map.items() if k not in (departure_icao, destination_icao)}
        # destination alternate: if parser provided destination_alternate, use it; else None
        dest_alts = data.get('destination_alternate')
        dest_alt_block = None
        if isinstance(dest_alts, list) and len(dest_alts) > 0:
            dest_alt_block = weather_map.get(dest_alts[0])
        # prepare canonical payload
        data = {
            'weather': {
                'departure': {departure_icao: departure_block} if departure_block else {},
                'enroute': enroute_block,
                'destination': {destination_icao: destination_block} if destination_block else {},
                'destination_alternate': {dest_alts[0]: dest_alt_block} if dest_alt_block else {}
            }
        }

    # Build system prompt and schema hints for complex sections
    system_prompt = (
        'You are a deterministic safety analysis assistant. Given a structured JSON representing one section of a flight plan, '
        'evaluate operational risk for that section. Return ONLY valid JSON. For multi-part sections (weather/notams) return JSON with keys:\n'
        "  - section: same as request\n"
        "  - by_part: object mapping each sub-part to an analysis object {risk_level, flags, details}\n"
        "For single-section analysis return {section, risk_level, flags, details}.\n"
        'Do not include operational commands or recommendations; this is advisory flag-only output.'
    )

    # Schema hint specifics
    schema_hint = ''
    if section == 'weather':
        schema_hint = ('Payload is {"weather": {"departure": {ICAO: {...}}, "enroute": {ICAO: {...}}, "destination": {...}, "destination_alternate": {...}}}. '
                       'Assess each of departure, enroute (all enroute airports), destination, and destination_alternate separately and return a by_part mapping where each value is {risk_level, flags, details}.')
    elif section == 'notams':
        schema_hint = ('Payload is {"notams": {"departure": {ICAO: ["..."]}, "destination": {...}, "enroute_alternates": {ICAO: [...]}, "etops_alternates": {ICAO: [...]}, "company": [...], "area": [...]}}. '
                       'Assess each airport individually and also provide assessments for company and area notams. Return a by_part mapping with keys departure,destination,enroute_alternates,etops_alternates,company,area. For enroute/etops provide a mapping ICAO->analysis.')

    # Truncate payload
    data_json = json.dumps(data) if data is not None else '{}'
    if len(data_json) > 18000:
        data_json = data_json[:18000] + '\n...[TRUNCATED]...'

    # DEBUG: log the payload being sent to the LLM for analysis
    try:
        full_len = len(json.dumps(data)) if data is not None else 0
        preview = data_json if len(data_json) <= 20000 else data_json[:20000] + '\n...[TRUNCATED]...'
        print(f'LLM analyze_section payload for section="{section}", full_length={full_len}')
        print('LLM analyze_section preview:\n', preview)
    except Exception:
        pass

    user_instructions = f'Analyze the following section "{section}". {schema_hint} Data:\n{data_json}'

    payload = {
        'model': 'deepseek-chat',
        'messages': [
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': user_instructions}
        ],
        'stream': False,
    }

    headers = {
        'Authorization': f'Bearer {_get_api_key()}',
        'Content-Type': 'application/json',
        'User-Agent': 'fplguru/1.0'
    }

    try:
        resp = requests.post(DEESEEK_API_URL, json=payload, headers=headers, timeout=timeout)
        resp.raise_for_status()
        resp_json = resp.json()
        assistant_text = None
        try:
            assistant_text = resp_json['choices'][0]['message']['content']
        except Exception:
            try:
                assistant_text = resp_json['choices'][0].get('text')
            except Exception:
                assistant_text = None
        if not assistant_text:
            raise RuntimeError('empty assistant content')

        assistant_text_clean = assistant_text.strip()
        assistant_text_clean = re.sub(r'^```(?:json)?\s*', '', assistant_text_clean, flags=re.IGNORECASE)
        assistant_text_clean = re.sub(r'\s*```$', '', assistant_text_clean, flags=re.IGNORECASE)

        try:
            parsed = json.loads(assistant_text_clean)
        except Exception as e_parse:
            m = re.search(r'(\{[\s\S]*\})', assistant_text_clean)
            if m:
                candidate = m.group(1)
                try:
                    parsed = json.loads(candidate)
                except Exception as e_parse2:
                    return {
                        'section': section,
                        'risk_level': 'unknown',
                        'flags': [],
                        'details': None,
                        'raw_llm_response_text': assistant_text_clean[:20000] if assistant_text_clean else None,
                        'llm_error': f'failed to parse assistant JSON: {str(e_parse2)}'
                    }
            else:
                return {
                    'section': section,
                    'risk_level': 'unknown',
                    'flags': [],
                    'details': None,
                    'raw_llm_response_text': assistant_text_clean[:20000] if assistant_text_clean else None,
                    'llm_error': f'failed to parse assistant JSON: {str(e_parse)}'
                }

        # If multi-part (weather/notams) expect 'by_part'
        if section in ('weather', 'notams'):
            # Validate shape
            by_part = parsed.get('by_part') if isinstance(parsed.get('by_part'), dict) else None
            if not by_part:
                # If assistant returned a flat mapping with keys for parts, try to coerce
                # Accept keys like 'departure','enroute','destination','destination_alternate','company','area'
                candidate_parts = {}
                for k in ('departure', 'enroute', 'destination', 'destination_alternate', 'enroute_alternates', 'etops_alternates', 'company', 'area'):
                    if k in parsed:
                        candidate_parts[k] = parsed[k]
                if candidate_parts:
                    return {
                        'section': section,
                        'by_part': candidate_parts,
                        'raw_llm_response_text': assistant_text[:20000] if assistant_text else None
                    }
                # Fallback: return unknown
                return {
                    'section': section,
                    'by_part': {},
                    'raw_llm_response_text': assistant_text[:20000] if assistant_text else None,
                    'llm_error': 'assistant did not return expected by_part mapping'
                }
            # Normalize each subpart to ensure it has risk_level, flags, details
            normalized = {}
            for part_key, part_val in by_part.items():
                if isinstance(part_val, dict):
                    # If this is a mapping of ICAO->analysis (for enroute), keep as-is but normalize leafs
                    if all(re.match(r'^[A-Z]{4}$', k) for k in part_val.keys() if isinstance(k, str)):
                        # ICAO mapping
                        normalized_icao_map = {}
                        for icao_k, icao_v in part_val.items():
                            icao_v = icao_v or {}
                            normalized_icao_map[icao_k] = {
                                'risk_level': icao_v.get('risk_level', 'unknown'),
                                'flags': icao_v.get('flags', []) or [],
                                'details': icao_v.get('details')
                            }
                        normalized[part_key] = normalized_icao_map
                    else:
                        normalized[part_key] = {
                            'risk_level': part_val.get('risk_level', 'unknown'),
                            'flags': part_val.get('flags', []) or [],
                            'details': part_val.get('details')
                        }
                else:
                    normalized[part_key] = {
                        'risk_level': 'unknown',
                        'flags': [],
                        'details': str(part_val) if part_val is not None else None
                    }
            return {
                'section': section,
                'by_part': normalized,
                'raw_llm_response_text': assistant_text[:20000] if assistant_text else None
            }

        # Legacy single-section return
        parsed.setdefault('section', section)
        parsed.setdefault('risk_level', 'unknown')
        parsed.setdefault('flags', [])
        parsed.setdefault('details', None)
        return {
            'section': parsed['section'],
            'risk_level': parsed['risk_level'],
            'flags': parsed['flags'],
            'details': parsed['details'],
            'raw_llm_response_text': assistant_text[:20000] if assistant_text else None,
        }

    except requests.exceptions.RequestException as e:
        return {
            'section': section,
            'risk_level': 'unknown',
            'flags': [],
            'details': None,
            'raw_llm_response_text': None,
            'llm_error': str(e),
        }
