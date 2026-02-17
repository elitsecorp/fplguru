import re
import io
from typing import Dict, Any
from PyPDF2 import PdfReader
from datetime import datetime

# pdfminer is a more robust fallback extractor for difficult PDFs
try:
    from pdfminer.high_level import extract_text as pdfminer_extract_text
except Exception:
    pdfminer_extract_text = None


def extract_text_from_pdf_bytes(b: bytes) -> str:
    """Extract text from PDF bytes. Try PyPDF2 first (page-by-page). If extraction appears incomplete
    (e.g., only a small amount of text for multi-page PDF) or file is encrypted, fall back to pdfminer if available.

    This function always attempts to extract text from all pages deterministically.
    """
    # First try PyPDF2 (fast)
    try:
        reader = PdfReader(io.BytesIO(b))
    except Exception:
        reader = None

    text = ""
    page_count = 0
    if reader:
        try:
            page_count = len(reader.pages)
            parts = []
            for p in reader.pages:
                try:
                    # extract_text() returns the textual content of this page
                    ptext = p.extract_text() or ""
                except Exception:
                    ptext = ""
                parts.append(ptext)
            text = "\n".join(parts).strip()
        except Exception:
            text = ""

    # If encrypted and PyPDF2 couldn't extract, try to decrypt with empty password then retry
    if reader and getattr(reader, 'is_encrypted', False) and not text:
        try:
            if reader.decrypt(''):
                parts = []
                for p in reader.pages:
                    try:
                        ptext = p.extract_text() or ""
                    except Exception:
                        ptext = ""
                    parts.append(ptext)
                text = "\n".join(parts).strip()
        except Exception:
            text = ""

    # Heuristic: if there are multiple pages but extracted text is very small, fall back to pdfminer
    if (page_count > 1 and (not text or len(text) < 200)) and pdfminer_extract_text is not None:
        try:
            text = pdfminer_extract_text(io.BytesIO(b)) or ""
        except Exception:
            # keep whatever we have
            pass

    # Final fallback: return whatever we have (possibly empty)
    return text


def _clean_number(s: str):
    if s is None:
        return None
    s = s.replace(',', '').strip()
    try:
        if '.' in s:
            return float(s)
        return float(s)
    except Exception:
        return None


def _try_parse_datetime(s: str):
    if not s:
        return None
    s = s.strip()
    # Try ISO format first
    try:
        return datetime.fromisoformat(s)
    except Exception:
        pass
    # Common patterns
    fmts = [
        '%Y-%m-%d %H:%M',
        '%Y-%m-%d %H:%M:%S',
        '%d %b %Y %H:%M',
        '%d %b %Y %H:%M:%S',
        '%d/%m/%Y %H:%M',
        '%d/%m/%Y %H:%M:%S',
    ]
    for f in fmts:
        try:
            return datetime.strptime(s, f)
        except Exception:
            continue
    return None


def parse_text_to_flightplan(text: str) -> Dict[str, Any]:
    """
    Deterministic, regex-based extraction. If a value cannot be determined it is left as None and
    the caller should flag the missing field (parser marks missing fields explicitly).

    This version includes specialized extraction for OFP header blocks as in the sample provided.
    """
    import os
    fp: Dict[str, Any] = {}
    missing = []

    # If configured, delegate extraction to the LLM-based extractor (useful for very messy OFPs).
    # Controlled by environment variable FPL_USE_LLM=1 to avoid accidental external calls.
    if os.environ.get('FPL_USE_LLM') == '1':
        try:
            # local import to avoid hard dependency at module import time
            from services.llm_parser import extract_flightplan_from_text
            llm_result = extract_flightplan_from_text(text)
            # ensure we return the raw_text for auditing as previously
            llm_result['raw_text'] = text
            llm_result['raw_text_snippet'] = text[:2000]
            return llm_result
        except Exception:
            # on failure fall back to rule-based parsing below
            pass

    # Try to isolate header (before the first dashed separator) which contains many summary fields
    parts = text.split('\n--------------------------------------------------------------------\n')
    header = parts[0] if parts else text

    # Callsign: prefer explicit 'Callsign' label but fall back to CFP header like 'ET3734/07FEB'
    m = re.search(r'Callsign[:\s]*([A-Z0-9\-]+)', text, re.IGNORECASE)
    if m:
        fp['callsign'] = m.group(1)
    else:
        m = re.search(r'CFP ID[\s\S]{0,120}?\b([A-Z0-9]+)/(?:\d{2}[A-Z]{3})', header, re.IGNORECASE)
        if not m:
            # Fallback: pattern like 'ET3734/07FEB' near top of document
            m = re.search(r'\b([A-Z]{2}\d{1,4})/\d{2}[A-Z]{3}', header)
        fp['callsign'] = m.group(1) if m else None
    if not fp['callsign']:
        missing.append('callsign')

    # STD / STA (from header)
    m = re.search(r'STD\s*([0-9]{3,4})Z', header)
    if m:
        s = m.group(1).zfill(4)
        fp['time_departure'] = f"{s[:2]}:{s[2:]}:00Z"
    m2 = re.search(r'STA\s*([0-9]{3,4})Z', header)
    if m2:
        s2 = m2.group(1).zfill(4)
        fp['time_arrival'] = f"{s2[:2]}:{s2[2:]}:00Z"

    # Distances
    m = re.search(r'GND\s*DIST\s*([0-9]+)', header)
    if m:
        fp['ground_distance'] = _clean_number(m.group(1))
    m = re.search(r'AIR\s*DIST\s*([0-9]+)', header)
    if m:
        fp['air_distance'] = _clean_number(m.group(1))

    # Average wind at top summary (e.g., AVG WIND   247/026)
    m = re.search(r'AVG\s*WIND\s*([0-9]{1,3})/([0-9]{1,3})', header)
    if m:
        try:
            fp.setdefault('weather', {})
            fp['weather'].setdefault('takeoff', {})
            fp['weather']['takeoff']['wind_dir_deg'] = int(m.group(1))
            fp['weather']['takeoff']['wind_speed_kt'] = int(m.group(2))
        except Exception:
            pass

    # Weights summary (MTOW, MLAW, MZFW, DOW)
    m = re.search(r'MTOW\s*([0-9]+\.?[0-9]*)', header)
    if m:
        fp['mtow'] = _clean_number(m.group(1))
    m = re.search(r'MLAW\s*([0-9]+\.?[0-9]*)', header)
    if m:
        fp['mlaw'] = _clean_number(m.group(1))
    m = re.search(r'MZFW\s*([0-9]+\.?[0-9]*)', header)
    if m:
        fp['zerofuel_weight'] = _clean_number(m.group(1))
    m = re.search(r'DOW\s*([0-9]+\.?[0-9]*)', header)
    if m:
        fp['dow'] = _clean_number(m.group(1))

    # ETOW / ELAW / EZFW
    m = re.search(r'ETOW\s*([0-9]+\.?[0-9]*)', header)
    if m:
        fp['etow'] = _clean_number(m.group(1))
    m = re.search(r'ELAW\s*([0-9]+\.?[0-9]*)', header)
    if m:
        fp['elaw'] = _clean_number(m.group(1))
    m = re.search(r'EZFW\s*([0-9]+\.?[0-9]*)', header)
    if m:
        fp['ezfw'] = _clean_number(m.group(1))

    # Trip / CONTMIN / ALTN / MINTOF / TAXI / BLOCK FUEL - search entire document (not only header)
    m = re.search(r'\bTRIP\s+([0-9]+)\s+([0-9]{1,2}\.[0-9]{2})', text)
    if m:
        fp['trip_fuel'] = _clean_number(m.group(1))
        fp['trip_time'] = m.group(2)
    m = re.search(r'\bCONTMIN\s+([0-9]+)\s+([0-9]{1,2}\.[0-9]{2})', text)
    if m:
        fp['contingency'] = _clean_number(m.group(1))
        fp['contingency_time'] = m.group(2)
    # ALTN line e.g. 'ALTN          3893  00.41  LEMD'
    m = re.search(r'\bALTN\s+([0-9]+)\s+([0-9]{1,2}\.[0-9]{2})\s+([A-Z]{4})', text)
    if m:
        fp['alternate_distance'] = _clean_number(m.group(1))
        fp['alternate_time'] = m.group(2)
        fp['destination_alternate'] = m.group(3)
    # MINTOF and CORR MINTOF
    m = re.search(r'\bMINTOF\s+([0-9]+)', text)
    if m:
        fp['minimum_takeoff_fuel'] = _clean_number(m.group(1))
    m = re.search(r'CORR(?:ECTED)?\s+MINTOF\s+([0-9]+)', text, re.IGNORECASE)
    if m:
        fp['corrected_minimum_takeoff_fuel'] = _clean_number(m.group(1))
    # TAXI and BLOCK FUEL
    m = re.search(r'\bTAXI\s+([0-9]+)\s+[0-9]{2}\.[0-9]{2}', text)
    if m:
        fp['taxi'] = _clean_number(m.group(1))
    m = re.search(r'\bBLOCK\s*FUEL\s+([0-9]+)', text)
    if m:
        fp['block_fuel'] = _clean_number(m.group(1))

    # Departure and Destination ICAO attempt: look for pattern like 'EHBK/... LEZG/...'
    m = re.search(r'\b([A-Z]{4})/[^\n]*?\s+([A-Z]{4})\b', header)
    if m:
        fp['departure'] = m.group(1)
        fp['destination'] = m.group(2)
    else:
        # Fallback: from ATC Flight Plan block (FPL- line) search first occurrence of '-EHBK' and '-LEZG'
        m2 = re.search(r'-([A-Z]{4})\d*\s', text)
        if m2:
            fp['departure'] = fp.get('departure') or m2.group(1)
        m3 = re.search(r'\s-([A-Z]{4})\b', text)
        if m3:
            fp['destination'] = fp.get('destination') or m3.group(1)

    # Now fall back to earlier generic extraction for fields that remain
    def find_numeric(label_variants):
        for lbl in label_variants:
            regex = rf'{lbl}[:\s]*([0-9\,\.]+)\s*(kg|KG|kgs|KGs|NM|nm|ft|m)?'
            m = re.search(regex, text, re.IGNORECASE)
            if m:
                return _clean_number(m.group(1))
        return None

    if 'takeoff_weight' not in fp:
        fp['takeoff_weight'] = fp.get('mtow') or find_numeric(['Takeoff weight', 'TakeoffWeight', 'TOW', 'MTOW'])
    if 'landing_weight' not in fp:
        fp['landing_weight'] = fp.get('mlaw') or find_numeric(['Landing weight', 'LandingWeight', 'LAW', 'MLAW'])
    if 'zerofuel_weight' not in fp:
        fp['zerofuel_weight'] = fp.get('zerofuel_weight') or find_numeric(['Zero fuel weight', 'ZeroFuelWeight', 'ZFW', 'MZFW'])
    if 'ground_distance' not in fp:
        fp['ground_distance'] = fp.get('ground_distance') or find_numeric(['Ground distance', 'Distance', 'GroundDistance', 'GND DIST'])

    # Fuel figures fallback already extracted above; ensure corrected_minimum_takeoff_fuel from CORR MINTOF as alternate label
    if 'corrected_minimum_takeoff_fuel' not in fp or fp.get('corrected_minimum_takeoff_fuel') is None:
        m = re.search(r'CORR(?:ECTED)?\s+MINTOF\s+([0-9]+)', text, re.IGNORECASE)
        if m:
            fp['corrected_minimum_takeoff_fuel'] = _clean_number(m.group(1))

    # Route text: Prefer the route line found between the first pair of dashed separators
    route_text = None
    try:
        sep_block = re.search(r'\n-{4,}\n([\s\S]{1,400}?)\n-{4,}\n', text)
        if sep_block:
            block = sep_block.group(1).strip()
            # choose the first non-empty line that looks like a route (contains '/' or multiple uppercase tokens)
            for ln in block.splitlines():
                ln = ln.strip()
                if not ln:
                    continue
                if '/' in ln or len(re.findall(r'\b[A-Z]{3,}\b', ln)) >= 2:
                    route_text = ln
                    break
            # if nothing matched, take the first non-empty line as fallback
            if not route_text:
                for ln in block.splitlines():
                    ln = ln.strip()
                    if ln:
                        route_text = ln
                        break
        # Normalize whitespace if found
        if route_text:
            fp['route_text'] = ' '.join(route_text.split())
        else:
            # previous fallback: find the first multi-line sequence of waypoints in the whole text
            m = re.search(r'\n([A-Z0-9\s,\-/]{30,}\n(?:[A-Z0-9\s,\-/]{30,}\n){0,4})', text)
            if m:
                route_text = m.group(1).strip()
                fp['route_text'] = ' '.join(route_text.split())
            else:
                m = re.search(r'ROUTE[:\s]*([A-Z0-9\s\-/]{10,200})', text, re.IGNORECASE)
                fp['route_text'] = m.group(1).strip() if m else None
    except Exception:
        fp['route_text'] = fp.get('route_text') if fp.get('route_text') else None

    # Alternates and ETOPS
    m = re.search(r'Destination Alternate[s]?:[\s]*([A-Z]{4}(?:[,\s]+[A-Z]{4})*)', text, re.IGNORECASE)
    if m and not fp.get('destination_alternate'):
        alts = re.findall(r'([A-Z]{4})', m.group(1))
        fp['destination_alternate'] = alts if len(alts) > 1 else (alts[0] if alts else None)

    m = re.search(r'ETOPS[:\s]*Yes', text, re.IGNORECASE)
    fp['is_etops'] = bool(m)
    m = re.search(r'ETOPS Alternates?:[\s]*([A-Z]{4}(?:[,\s]+[A-Z]{4})*)', text, re.IGNORECASE)
    if m:
        fp['etops_alternates'] = re.findall(r'([A-Z]{4})', m.group(1))
    else:
        fp.setdefault('etops_alternates', [] if fp.get('is_etops') else None)

    # Weather sections: look for headers like "Takeoff weather" etc. Preserve any takeoff wind parsed earlier.
    weather_sections = fp.get('weather', {})

    # 1) Try to extract airport-specific METAR/TAF style blocks (sample format uses airport header line then indented SA / FT lines)
    airport_block_re = re.compile(r'(?m)^(?P<header>[A-Z]{4}/[^\n]+)\n(?P<body>(?:\s{2,}[^\n]+\n)+)')
    for m in airport_block_re.finditer(text):
        header = m.group('header').strip()
        body = m.group('body')
        # Extract ICAO code from header (e.g., 'EHBK/MST  MAASTRICHT/AACHEN')
        icao_m = re.search(r'([A-Z]{4})', header)
        icao = icao_m.group(1) if icao_m else None
        if not icao:
            continue

        # SA line often contains quick METAR-like summary and FT is the longer TAF block
        sa_m = re.search(r'\bSA\s+([0-9]{6}.*?)=', body, re.DOTALL)
        ft_m = re.search(r'\bFT\s+([0-9]{6}.*?)=', body, re.DOTALL)

        entry = {
            'raw': body.strip()
        }
        if sa_m:
            entry['sa'] = sa_m.group(1).strip()
            # try to extract wind like 15008KT or 150/08
            w = re.search(r'(\b\d{3}[0-9]{2,3}KT\b)|(\b\d{1,3}/\d{1,3}\b)', sa_m.group(1))
            if w:
                if w.group(1):
                    dir_sp = re.search(r'(\d{3})(\d{2,3})KT', w.group(1))
                    if dir_sp:
                        entry['wind_dir_deg'] = int(dir_sp.group(1))
                        entry['wind_speed_kt'] = int(dir_sp.group(2))
                else:
                    d = w.group(2).split('/')
                    try:
                        entry['wind_dir_deg'] = int(d[0])
                        entry['wind_speed_kt'] = int(d[1])
                    except Exception:
                        pass
        if ft_m:
            entry['ft'] = ft_m.group(1).strip()

        # Heuristic: assign to takeoff/destination/enroute based on match to departure/destination ICAOs
        if icao == fp.get('departure'):
            weather_sections.setdefault('takeoff', {}).update({icao: entry})
        elif icao == fp.get('destination'):
            weather_sections.setdefault('destination', {}).update({icao: entry})
        else:
            weather_sections.setdefault('enroute', {}).update({icao: entry})

    # 2) If no per-airport blocks found, fallback to searching for generic named sections as before
    if not weather_sections:
        for section in ['takeoff', 'enroute', 'etops', 'destination']:
            sec_re = re.search(rf'{section}\s+weather[:\n]([\s\S]{{0,4000}}?)(?:\n\n|$)', text, re.IGNORECASE)
            if sec_re:
                weather_text = sec_re.group(1)
                wd = re.search(r'wind\s*dir[:\s]*([0-9]+)', weather_text, re.IGNORECASE)
                ws = re.search(r'wind\s*speed[:\s]*([0-9]+)', weather_text, re.IGNORECASE)
                temp = re.search(r'temp(?:erature)?[:\s]*(-?[0-9]+)', weather_text, re.IGNORECASE)
                cb = re.search(r'cloud base[:\s]*([0-9]+)\s*ft', weather_text, re.IGNORECASE)
                rvr = re.search(r'RVR[:\s]*([0-9]+)', weather_text, re.IGNORECASE)
                weather_sections[section] = {
                    'wind_dir_deg': int(wd.group(1)) if wd else None,
                    'wind_speed_kt': int(ws.group(1)) if ws else None,
                    'temperature_c': int(temp.group(1)) if temp else None,
                    'cloud_base_ft': int(cb.group(1)) if cb else None,
                    'rvr_m': int(rvr.group(1)) if rvr else None,
                    'raw': weather_text.strip(),
                }

    fp['weather'] = weather_sections

    # NOTAM sections: more robust extraction tuned for sample layouts
    # Clean common page/footer noise and ET markers before multi-line captures
    clean_text = re.sub(r'Page\s*\d+\s*of\s*\d+', ' ', text, flags=re.IGNORECASE)
    clean_text = re.sub(r'\n\s*ET\s*\S[^\n]*Reg:[^\n]*', '\n', clean_text)
    clean_text = re.sub(r'ET\s*\d{3,}\/[^\s\n]*[^\n]*', '', clean_text)
    clean_text = re.sub(r'\n\s*\n+', '\n\n', clean_text)

    # Note: aggregated full NOTAM block (lido_notam / notams) removed by design.
    # We only keep per-airport NOTAM segmentation under 'airport_notams' / 'notams_by_airport'.

    # Extract airport-specific sections (DEPARTURE AIRPORT, DESTINATION AIRPORT, DEPARTURE ALTERNATE, DESTINATION ALTERNATE, ENROUTE AIRPORT)
    airport_sections = {}
    headings = [
        'DEPARTURE AIRPORT', 'DEPARTURE ALTERNATE', 'DESTINATION AIRPORT', 'DESTINATION ALTERNATE',
        'ETOPS ALTERNATE', 'ETOPS ALTERNATE AIRPORT', 'ETOPS ALTERNATE AIRPORT(S)', 'ETOPS ALTERNATE(S)',
        'ENROUTE AIRPORT', 'ENROUTE AIRPORT(S)', 'EXTENDED AREA AROUND DEPARTURE', 'EXTENDED AREA AROUND DESTINATION'
    ]
    for h in headings:
        try:
            # match patterns like '\n===\nHEADING\n===\n' or the heading line alone
            pattern = rf'{re.escape(h)}\s*\n=+\s*\n([\s\S]{{0,20000}}?)(?=\n[A-Z ]{{3,40}}\n=+\s*\n|\n\s*DEPARTURE AIRPORT\b|\n\s*DESTINATION AIRPORT\b|\n\s*DEPARTURE ALTERNATE\b|\n\s*DESTINATION ALTERNATE\b|\n\s*ENROUTE AIRPORT\b|\Z)'
            msec = re.search(pattern, clean_text, re.IGNORECASE)
            if not msec:
                # Fallback: heading line without surrounding =====
                pattern2 = rf'{re.escape(h)}\s*\n([\s\S]{{0,20000}}?)(?=\n[A-Z ]{{3,40}}\n=+\s*\n|\n\s*DEPARTURE AIRPORT\b|\n\s*DESTINATION AIRPORT\b|\n\s*DEPARTURE ALTERNATE\b|\n\s*DESTINATION ALTERNATE\b|\n\s*ENROUTE AIRPORT\b|\Z)'
                msec = re.search(pattern2, clean_text, re.IGNORECASE)
            if msec:
                airport_sections[h] = msec.group(1).strip()
        except Exception:
            continue

    # Map airport sections into fp fields for easier operator review
    if 'DEPARTURE AIRPORT' in airport_sections:
        fp['departure_notams'] = airport_sections['DEPARTURE AIRPORT']
    else:
        fp.setdefault('departure_notams', None)
    if 'DESTINATION AIRPORT' in airport_sections:
        fp['destination_notams'] = airport_sections['DESTINATION AIRPORT']
    else:
        fp.setdefault('destination_notams', None)
    if 'DEPARTURE ALTERNATE' in airport_sections:
        fp['departure_alternate_notams'] = airport_sections['DEPARTURE ALTERNATE']
    else:
        fp.setdefault('departure_alternate_notams', None)
    if 'DESTINATION ALTERNATE' in airport_sections:
        fp['destination_alternate_notams'] = airport_sections['DESTINATION ALTERNATE']
    else:
        fp.setdefault('destination_alternate_notams', None)
    # ETOPS alternates
    etops_keys = ['ETOPS ALTERNATE', 'ETOPS ALTERNATE AIRPORT', 'ETOPS ALTERNATE AIRPORT(S)', 'ETOPS ALTERNATE(S)']
    for k in etops_keys:
        if k in airport_sections:
            fp['etops_alternate_notams'] = airport_sections[k]
            break
    else:
        fp.setdefault('etops_alternate_notams', None)
    # Enroute may be under ENROUTE AIRPORT(S) or EXTENDED AREA headers
    enroute_texts = []
    for key in ('ENROUTE AIRPORT', 'ENROUTE AIRPORT(S)', 'EXTENDED AREA AROUND DEPARTURE', 'EXTENDED AREA AROUND DESTINATION'):
        if key in airport_sections:
            enroute_texts.append(airport_sections[key])
    if enroute_texts:
        fp['enroute_notams'] = '\n\n'.join(enroute_texts)
    else:
        fp.setdefault('enroute_notams', None)
    # If ETOPS alternate blocks present, also merge them into enroute_notams if appropriate
    if fp.get('etops_alternate_notams') and not fp.get('enroute_notams'):
        fp['enroute_notams'] = fp['etops_alternate_notams']

    # Segment airport-specific notams into per-airport entries
    fp.setdefault('airport_notams', {})

    # Helper: expand common NOTAM abbreviations into human-readable phrases
    def _expand_abbrevs(s: str) -> str:
        if not s:
            return s
        # common mapping - keep conservative and auditable
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

    # Helper: wrap long paragraphs to a readable width while preserving paragraph breaks
    def _wrap_text(s: str, width: int = 80) -> str:
        import textwrap
        if not s:
            return s
        paras = [p.strip() for p in s.split('\n\n') if p.strip()]
        wrapped_paras = [textwrap.fill(p, width=width) for p in paras]
        return '\n\n'.join(wrapped_paras)

    for heading, block in airport_sections.items():
        if not block:
            continue
        # find ICAO code in the heading or block (first 4-letter token)
        icao_m = re.search(r'\b([A-Z]{4})\b', heading) or re.search(r'\b([A-Z]{4})\b', block)
        icao = icao_m.group(1) if icao_m else None
        if not icao:
            # skip blocks without obvious ICAO
            continue
        # Split block into individual entries by looking for lines that start with NOTAM/ID codes like '1A409/26', 'CO31/20', 'SX58/25', '1D575/25'
        parts = re.split(r'(?=^\s*[A-Z0-9]{1,4}\d{1,5}/\d{2})', block, flags=re.MULTILINE)
        entries = [p.strip() for p in parts if p and p.strip()]
        # If no numbered entries found, fallback to splitting on double-newlines between items
        if not entries:
            entries = [p.strip() for p in re.split(r'\n\s*\n', block) if p.strip()]
        if entries:
            fp['airport_notams'][icao] = entries

    # Build a structured per-airport NOTAM mapping for easier JSON consumption
    fp.setdefault('notams_by_airport', {})
    for icao, entries in fp.get('airport_notams', {}).items():
        try:
            # Combine entries, expand abbreviations and wrap long lines for readability
            combined = '\n\n'.join(entries)
            expanded = _expand_abbrevs(combined)
            wrapped = _wrap_text(expanded, width=80)

            # Simple keyword-based risk tagging (conservative, auditable)
            risk_keywords = {
                'closure': ['closed', 'closure', 'shut'],
                'contamination': ['contaminat', 'slush', 'ice', 'snow', 'water on runway', 'frozen', 'frost'],
                'braking': ['braking', 'poor braking', 'mu value', 'slippery', 'contam'],
                'reduced_visibility': ['fog', 'mist', 'haze', 'rvr', 'visibility'],
                'thunderstorms': ['thunderstorm', 'ts', 'lightning'],
                'runway_damage': ['crack', 'pothole', 'damag', 'surface irregularit'],
                'navaid_issues': ['navaid', 'vordme out', 'ils out', 'papi out', 'nav']
            }
            found = set()
            low = expanded.lower()
            for tag, kws in risk_keywords.items():
                for kw in kws:
                    if kw in low:
                        found.add(tag)
                        break
            risks = sorted(found)

            fp['notams_by_airport'][icao] = {
                'entries': entries,
                # Human-readable description: first state the airport then list risks and the wrapped description
                'description': f"{icao}: Risks: {', '.join(risks) if risks else 'none identified'}\n\n{wrapped}",
                'risks': risks
            }
        except Exception:
            fp['notams_by_airport'][icao] = {'entries': entries, 'description': None, 'risks': []}

    # 3) Company NOTAMs: capture blocks headed by 'COMPANY NOTAM' (often inside +++ separators)
    # Also capture standalone COxxx NOTAM entries (e.g., 'CO31/20') and join them.
    company_sections = []
    # Blocks with 'COMPANY NOTAM' header
    for m in re.finditer(r'(^\+{3,}[\s\S]{0,200}?\+{3,}\s*\n)?^\s*COMPANY(?:\s|/)?NOTAM[S]?\b[\s\S]{0,2000}?(?=\n={2,}|\n[A-Z ]{3,40}\n|\n\+{3,}|\nWX/NOTAM|\nCREW ALERT|\Z)', clean_text, re.IGNORECASE | re.MULTILINE):
        company_sections.append(m.group(0).strip())
    # Standalone CO entries
    co_entries = re.findall(r'(^CO\d{1,5}/\d{2}[\s\S]{0,500}?)(?=\n\s*\n|\n[A-Z ]{3,40}\n|\Z)', clean_text, re.IGNORECASE | re.MULTILINE)
    for c in co_entries:
        company_sections.append(c.strip())
    if company_sections:
        # join and keep reasonable limit
        fp['company_notams'] = '\n\n'.join(company_sections)[:8000]
    else:
        fp.setdefault('company_notams', fp.get('company_notams'))

    # 4) Area NOTAMs: capture explicit 'AREA NOTAM' blocks, AIP-REGULATION or LIDO RMK sections
    area_sections = []
    area_matches = re.findall(r'AREA NOTAM[S]?:[\s\S]{0,2000}?(?=\n={2,}|\n[A-Z ]{3,40}\n|\Z)', clean_text, re.IGNORECASE)
    area_sections.extend(s.strip() for s in area_matches)
    # capture substantive 'AIP-REGULATION' or 'AIP' blocks (ignore isolated 'AIP' tokens)
    aip_matches = []
    # AIP-REGULATION with following block
    aip_matches += re.findall(r'\bAIP[- ]?REGULATION\b[^\n]*\n[\s\S]{20,1200}?(?=\n[A-Z ]{3,40}\n=+|\n={2,}|\nWX/NOTAM|\nCREW ALERT|\Z)', clean_text, re.IGNORECASE)
    # AIP header followed by substantive block (at least 20 chars)
    aip_matches += re.findall(r'\bAIP\b[^\n]*\n[\s\S]{20,1200}?(?=\n[A-Z ]{3,40}\n=+|\n={2,}|\nWX/NOTAM|\nCREW ALERT|\Z)', clean_text, re.IGNORECASE)
    # LIDO RMK blocks
    lido_rmks = re.findall(r'\bLIDO RMK\b[\s\S]{20,1200}?', clean_text, re.IGNORECASE)
    # combine, strip and filter short/duplicate matches
    combined_aip = []
    for s in (aip_matches + lido_rmks):
        ss = s.strip()
        if len(ss) < 20:
            continue
        if ss in combined_aip:
            continue
        combined_aip.append(ss)
    area_sections.extend(combined_aip)
    if area_sections:
        fp['area_notams'] = '\n\n'.join(area_sections)[:8000]
    else:
        fp.setdefault('area_notams', fp.get('area_notams'))

    # Backwards-compatible company_area_notams
    if not fp.get('company_area_notams'):
        fp['company_area_notams'] = fp.get('company_notams') or fp.get('area_notams') or None

    # Build consolidated `notams` JSON following the requested schema
    departure_icao = fp.get('departure')
    destination_icao = fp.get('destination')
    etops_list = fp.get('etops_alternates') or []

    notams = {
        'departure': {},
        'destination': {},
        'enroute_alternates': {},
        'etops_alternates': {},
        'company': [],
        'area': []
    }

    for icao, entries in fp.get('airport_notams', {}).items():
        if not entries:
            continue
        cleaned_entries = []
        for e in entries:
            # expand abbreviations and collapse whitespace/newlines into a single readable line
            exp = _expand_abbrevs(e)
            exp = re.sub(r'\s+', ' ', exp).strip()
            cleaned_entries.append(exp)
        if icao == departure_icao:
            notams['departure'][icao] = cleaned_entries
        elif icao == destination_icao:
            notams['destination'][icao] = cleaned_entries
        elif icao in etops_list:
            notams['etops_alternates'][icao] = cleaned_entries
        else:
            notams['enroute_alternates'][icao] = cleaned_entries

    # Company notams -> list
    if fp.get('company_notams'):
        comps = [re.sub(r'\s+', ' ', _expand_abbrevs(p)).strip() for p in re.split(r'\n\s*\n', fp['company_notams']) if p.strip()]
        notams['company'] = comps

    # Area notams -> list
    if fp.get('area_notams'):
        areas = [re.sub(r'\s+', ' ', _expand_abbrevs(p)).strip() for p in re.split(r'\n\s*\n', fp['area_notams']) if p.strip()]
        notams['area'] = areas

    # Attach consolidated notams while keeping older structures for backward compatibility
    fp['notams'] = notams

    # Build a minimal, strict schema to return (only the requested keys)
    # flight_number, route, weights, fuel, weather (per-airport), notams
    # We will construct 'weather' as a mapping ICAO -> {takeoff/enroute/destination/etops entries}
    weather_by_airport = {}
    ws = fp.get('weather', {}) or {}
    # ws may contain per-airport segments (dicts keyed by ICAO) or generic named segments
    for seg in ('takeoff', 'destination', 'enroute', 'etops'):
        seg_val = ws.get(seg)
        if isinstance(seg_val, dict):
            # If keys look like ICAO codes, assign per-airport; otherwise treat as generic and map to dep/dest
            # e.g., seg_val = {'EHBK': {...}}
            has_icao_keys = any(re.match(r'^[A-Z]{4}$', k) for k in seg_val.keys())
            if has_icao_keys:
                for k, v in seg_val.items():
                    if not k:
                        continue
                    weather_by_airport.setdefault(k, {})[seg] = v
            else:
                # generic block -> map to departure/destination where sensible
                if seg == 'takeoff' and fp.get('departure'):
                    weather_by_airport.setdefault(fp['departure'], {})[seg] = seg_val
                elif seg == 'destination' and fp.get('destination'):
                    weather_by_airport.setdefault(fp['destination'], {})[seg] = seg_val
                else:
                    # place under a generic key to avoid data loss
                    weather_by_airport.setdefault('GENERIC', {})[seg] = seg_val
        elif seg_val:
            # seg_val present but not a dict (unlikely) -> attach to GENERIC
            weather_by_airport.setdefault('GENERIC', {})[seg] = seg_val

    # Compose minimal schema
    minimal = {
        'flight_number': fp.get('callsign'),
        'route': fp.get('route_text'),
        'departure': fp.get('departure'),
        'destination': fp.get('destination'),
        'destination_alternate': fp.get('destination_alternate'),
        'weights': {
            'takeoff_weight': fp.get('takeoff_weight'),
            'landing_weight': fp.get('landing_weight'),
            'zerofuel_weight': fp.get('zerofuel_weight')
        },
        'fuel': {
            'trip_fuel': fp.get('trip_fuel'),
            'contingency': fp.get('contingency'),
            'minimum_takeoff_fuel': fp.get('minimum_takeoff_fuel'),
            'corrected_minimum_takeoff_fuel': fp.get('corrected_minimum_takeoff_fuel'),
            'block_fuel': fp.get('block_fuel'),
            'taxi': fp.get('taxi')
        },
        # weather per-airport mapping
        'weather': weather_by_airport,
        # notams in the requested consolidated shape
        'notams': fp.get('notams') or {}
    }

    # Return only the strict minimal JSON (no extra metadata)
    return minimal


def parse_pdf_file(file_bytes: bytes, use_llm: bool = None, timeout: int = 20):
    """Parse PDF bytes and return a strict minimal flightplan JSON schema.

    Returns only the minimal JSON with keys:
      - flight_number
      - route
      - weights: {takeoff_weight, landing_weight, zerofuel_weight}
      - fuel: {trip_fuel, contingency, minimum_takeoff_fuel, corrected_minimum_takeoff_fuel, block_fuel, taxi}
      - weather: mapping ICAO -> {takeoff/destination/enroute/etops}
      - notams: consolidated schema

    This function will run the deterministic parser first. If required fields are missing and
    LLM augmentation is enabled it will call the extractor but will NOT overwrite non-null rule-based values.
    """
    import os
    from .llm_parser import extract_flightplan_from_text
    import copy

    text = extract_text_from_pdf_bytes(file_bytes)

    # Run deterministic rule-based parser which now returns the minimal schema directly
    try:
        rule_minimal = parse_text_to_flightplan(text)
    except Exception:
        rule_minimal = None

    # If parser did not return the minimal shape, try to extract flightplan key (legacy)
    rule_fp = {}
    if isinstance(rule_minimal, dict) and 'flight_number' in rule_minimal:
        rule_fp = rule_minimal
    elif isinstance(rule_minimal, dict) and 'flightplan' in rule_minimal and isinstance(rule_minimal['flightplan'], dict):
        # legacy shape: map to minimal
        lp = rule_minimal['flightplan']
        # mapping helper
        rule_fp = {
            'flight_number': lp.get('callsign'),
            'route': lp.get('route_text'),
            'weights': {
                'takeoff_weight': lp.get('takeoff_weight'),
                'landing_weight': lp.get('landing_weight'),
                'zerofuel_weight': lp.get('zerofuel_weight')
            },
            'fuel': {
                'trip_fuel': lp.get('trip_fuel'),
                'contingency': lp.get('contingency'),
                'minimum_takeoff_fuel': lp.get('minimum_takeoff_fuel'),
                'corrected_minimum_takeoff_fuel': lp.get('corrected_minimum_takeoff_fuel'),
                'block_fuel': lp.get('block_fuel'),
                'taxi': lp.get('taxi')
            },
            'weather': lp.get('weather') or {},
            'notams': lp.get('notams') or {}
        }
    else:
        # failed parse -> empty minimal template
        rule_fp = {
            'flight_number': None,
            'route': None,
            'weights': {'takeoff_weight': None, 'landing_weight': None, 'zerofuel_weight': None},
            'fuel': {'trip_fuel': None, 'contingency': None, 'minimum_takeoff_fuel': None, 'corrected_minimum_takeoff_fuel': None, 'block_fuel': None, 'taxi': None},
            'weather': {},
            'notams': {}
        }

    # Decide whether to attempt LLM-based augmentation
    if use_llm is None:
        use_llm = os.getenv('FPL_USE_LLM', '0') == '1'

    # Define minimal required presence for conservative augmentation
    def _is_present_minimal(fp_min):
        if not fp_min.get('flight_number'):
            return False
        if not fp_min.get('route'):
            return False
        # require at least trip_fuel and one weight
        fuels = fp_min.get('fuel', {})
        weights = fp_min.get('weights', {})
        if fuels.get('trip_fuel') in (None, '', []):
            return False
        if weights.get('takeoff_weight') in (None, '', []):
            return False
        # require notams mapping (may be empty dict but present)
        if 'notams' not in fp_min:
            return False
        return True

    if _is_present_minimal(rule_fp):
        return rule_fp

    if not use_llm:
        return rule_fp

    # Call LLM to try to fill gaps, but DO NOT overwrite any non-null rule-based values
    try:
        llm_out = extract_flightplan_from_text(text, timeout=timeout)
    except Exception:
        return rule_fp

    # llm_out may be legacy-shape or may already contain minimal. Normalize to minimal.
    llm_fp_raw = None
    if isinstance(llm_out, dict):
        # prefer 'flightplan' key
        if 'flightplan' in llm_out and isinstance(llm_out['flightplan'], dict):
            llm_fp_raw = llm_out['flightplan']
        else:
            # maybe the LLM returned the minimal dict directly
            llm_fp_raw = llm_out
    if not isinstance(llm_fp_raw, dict):
        llm_fp_raw = {}

    # Map raw LLM keys to minimal schema
    def _map_llm_to_minimal(raw: dict) -> dict:
        mapped = {
            'flight_number': raw.get('callsign') or raw.get('flight_number') or None,
            'route': raw.get('route_text') or raw.get('route') or None,
            'departure': raw.get('departure') or raw.get('departure_icao') or None,
            'destination': raw.get('destination') or raw.get('destination_icao') or None,
            'destination_alternate': raw.get('destination_alternate') or raw.get('destination_alternates') or None,
            'weights': {
                'takeoff_weight': raw.get('takeoff_weight') or (raw.get('mtow') if raw.get('mtow') is not None else None),
                'landing_weight': raw.get('landing_weight') or raw.get('mlaw') or None,
                'zerofuel_weight': raw.get('zerofuel_weight') or raw.get('zerofuel_weight') or raw.get('mzfw') or None
            },
            'fuel': {
                'trip_fuel': raw.get('trip_fuel') or None,
                'contingency': raw.get('contingency') or None,
                'minimum_takeoff_fuel': raw.get('minimum_takeoff_fuel') or None,
                'corrected_minimum_takeoff_fuel': raw.get('corrected_minimum_takeoff_fuel') or None,
                'block_fuel': raw.get('block_fuel') or None,
                'taxi': raw.get('taxi') or None
            },
            'weather': raw.get('weather') or {},
            'notams': raw.get('notams') or {}
        }
        return mapped

    llm_min = _map_llm_to_minimal(llm_fp_raw)

    # Normalize LLM weather shape: if the LLM returned weather keyed by segments
    # (e.g. 'takeoff','destination','enroute','etops') convert it into an
    # ICAO-keyed mapping so the conservative merge logic below behaves correctly.
    try:
        wm = llm_min.get('weather') or {}
        if isinstance(wm, dict) and any(k in ('takeoff', 'destination', 'enroute', 'etops') for k in wm.keys()):
            normalized_wm = {}
            dep = rule_fp.get('departure')
            dest = rule_fp.get('destination')
            # map generic takeoff/destination blocks to the parsed departure/destination ICAOs
            if 'takeoff' in wm and dep:
                normalized_wm.setdefault(dep, {})['takeoff'] = wm.get('takeoff')
            if 'destination' in wm and dest:
                normalized_wm.setdefault(dest, {})['destination'] = wm.get('destination')
            # enroute may be an ICAO->obj mapping or a generic block
            if 'enroute' in wm:
                en = wm.get('enroute')
                if isinstance(en, dict) and all(re.match(r'^[A-Z]{4}$', k) for k in en.keys() if isinstance(k, str)):
                    for k, v in en.items():
                        normalized_wm.setdefault(k, {})['enroute'] = v
                else:
                    normalized_wm.setdefault('GENERIC', {})['enroute'] = en
            # etops similar handling
            if 'etops' in wm:
                et = wm.get('etops')
                if isinstance(et, dict) and all(re.match(r'^[A-Z]{4}$', k) for k in et.keys() if isinstance(k, str)):
                    for k, v in et.items():
                        normalized_wm.setdefault(k, {})['etops'] = v
                else:
                    normalized_wm.setdefault('GENERIC', {})['etops'] = et
            # replace weather in llm_min with normalized mapping
            llm_min['weather'] = normalized_wm
    except Exception:
        # keep original llm_min on failure
        pass

    # Conservative merge: fill only missing/null entries in rule_fp
    merged = copy.deepcopy(rule_fp)
    # top-level simple keys
    for k in ('flight_number', 'route', 'departure', 'destination', 'destination_alternate'):
        if merged.get(k) in (None, '', [] ) and llm_min.get(k) not in (None, '', []):
            merged[k] = llm_min[k]
    # weights and fuel: merge subkeys
    for sect in ('weights', 'fuel'):
        merged.setdefault(sect, {})
        for sk, sv in llm_min.get(sect, {}).items():
            if merged[sect].get(sk) in (None, '', []) and sv not in (None, '', []):
                merged[sect][sk] = sv
    # weather: only add airports not present
    merged.setdefault('weather', {})
    for icao, wv in (llm_min.get('weather') or {}).items():
        if icao not in merged['weather'] or not merged['weather'].get(icao):
            merged['weather'][icao] = wv
    # notams: merge keys conservatively
    merged.setdefault('notams', {})
    for sect in ('departure', 'destination', 'enroute_alternates', 'etops_alternates', 'company', 'area'):
        if not merged['notams'].get(sect) and llm_min.get('notams', {}).get(sect):
            merged['notams'][sect] = llm_min['notams'][sect]

    return merged
