import json
import os
from django.http import JsonResponse, HttpResponseBadRequest, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from services import analyzer, pdf_parser
from django.conf import settings
from .models import TelegramUser, FPLUpload
import hashlib, hmac, time
from django.utils import timezone

# Load thresholds once (deterministic)
THRESHOLDS = analyzer.load_thresholds(getattr(settings, 'THRESHOLDS_FILE', None))


@csrf_exempt
def analyze_fpl(request):
    if request.method != 'POST':
        return HttpResponseBadRequest(json.dumps({'error': 'POST required'}), content_type='application/json')
    try:
        payload = json.loads(request.body.decode('utf-8'))
    except Exception:
        return HttpResponseBadRequest(json.dumps({'error': 'invalid json'}), content_type='application/json')

    flightplan = payload.get('flightplan') or {}
    observations = payload.get('observations') or []

    result = analyzer.analyze_flightplan(flightplan, observations, THRESHOLDS)
    return JsonResponse(result, safe=False)


@csrf_exempt
def parse_pdf(request):
    """Accept a PDF file upload (multipart/form-data) or raw PDF bytes in the request body and return a parsed flightplan JSON.

    The endpoint is conservative: it returns parsed fields and an explicit data_quality list of missing/ambiguous fields.
    """
    if request.method != 'POST':
        return HttpResponseBadRequest(json.dumps({'error': 'POST required'}), content_type='application/json')

    # Temporary print of uploaded file keys (keep minimal)
    try:
        print(list(request.FILES.keys()))
    except Exception:
        # don't fail the request if printing fails
        pass

    file_obj = None
    if request.FILES:
        # Expecting form field named 'file'
        file_obj = request.FILES.get('file')
    file_bytes = None
    try:
        if file_obj:
            file_bytes = file_obj.read()
        else:
            # Fallback to raw body (application/pdf)
            file_bytes = request.body if request.body else None
    except Exception as e:
        return HttpResponseBadRequest(json.dumps({'error': 'failed to read uploaded file', 'detail': str(e)}), content_type='application/json')

    if not file_bytes:
        return HttpResponseBadRequest(json.dumps({'error': 'no file provided'}), content_type='application/json')

    # authenticate Telegram user from session (optional enforcement)
    tg_user = None
    try:
        tg_user_id = request.session.get('telegram_user_id')
        if tg_user_id:
            tg_user = TelegramUser.objects.filter(id=tg_user_id).first()
    except Exception:
        tg_user = None

    if tg_user:
        today = timezone.now().date()
        count_today = FPLUpload.objects.filter(user=tg_user, created_at__date=today).count()
        if count_today >= 2:
            return HttpResponseBadRequest(json.dumps({'error': 'quota_exceeded', 'message': 'Daily limit (2) reached'}), content_type='application/json')

    try:
        parsed = pdf_parser.parse_pdf_file(file_bytes)
    except Exception as e:
        return HttpResponseBadRequest(json.dumps({'error': 'failed to parse pdf', 'detail': str(e)}), content_type='application/json')

    # persist upload record when user present
    try:
        if tg_user:
            flight_number = parsed.get('flight_number') if isinstance(parsed, dict) else None
            FPLUpload.objects.create(user=tg_user, flight_number=flight_number, payload=parsed)
    except Exception:
        pass

    # DEBUG: print parsed flightplan (truncated) to server logs for diagnosis
    try:
        parsed_preview = json.dumps(parsed) if isinstance(parsed, dict) else str(parsed)
        if len(parsed_preview) > 2000:
            parsed_preview = parsed_preview[:2000] + '\n...[TRUNCATED]...'
        print('PARSED_FLIGHTPLAN_PREVIEW:', parsed_preview)
    except Exception:
        pass

    return JsonResponse(parsed, safe=False)


@csrf_exempt
def parse_with_llm(request):
    """Accepts JSON body: { "text": "..." } and returns LLM-extracted flightplan.

    The API key for Deepseek must be provided via environment variable FPL_DEEPSEEK_API_KEY. The server will
    not accept API keys in requests for security reasons.
    """
    if request.method != 'POST':
        return HttpResponseBadRequest(json.dumps({'error': 'POST required'}), content_type='application/json')
    try:
        payload = json.loads(request.body.decode('utf-8'))
    except Exception:
        return HttpResponseBadRequest(json.dumps({'error': 'invalid json'}), content_type='application/json')

    text = payload.get('text')
    if not text:
        return HttpResponseBadRequest(json.dumps({'error': 'missing text field'}), content_type='application/json')

    try:
        from services import llm_parser
        parsed = llm_parser.extract_flightplan_from_text(text)
    except Exception as e:
        return HttpResponseBadRequest(json.dumps({'error': 'llm extraction failed', 'detail': str(e)}), content_type='application/json')

    return JsonResponse(parsed, safe=False)


@csrf_exempt
def analyze_section(request):
    if request.method != 'POST':
        return HttpResponseBadRequest(json.dumps({'error': 'POST required'}), content_type='application/json')

    # DEBUG: print raw request body to help trace payload issues between frontend and server
    try:
        try:
            raw_preview = request.body.decode('utf-8', errors='replace')[:5000]
        except Exception:
            raw_preview = str(request.body)[:5000]
        print('ANALYZE_SECTION_RAW_BODY:', raw_preview)
    except Exception:
        pass

    try:
        payload = json.loads(request.body.decode('utf-8'))
    except Exception:
        return HttpResponseBadRequest(json.dumps({'error': 'invalid json'}), content_type='application/json')

    section = payload.get('section')
    data = payload.get('data')
    if not section or data is None:
        return HttpResponseBadRequest(json.dumps({'error': 'missing section or data'}), content_type='application/json')

    try:
        from services import llm_parser
        result = llm_parser.analyze_section(section, data)
    except Exception as e:
        return HttpResponseBadRequest(json.dumps({'error': 'analysis failed', 'detail': str(e)}), content_type='application/json')

    return JsonResponse(result, safe=False)


# Safe diagnostic endpoint to confirm environment variables presence to the running process.
# WARNING: this endpoint intentionally does NOT return the API key value.
@csrf_exempt
def debug_env(request):
    if request.method not in ('GET', 'POST'):
        return HttpResponseBadRequest(json.dumps({'error': 'GET or POST required'}), content_type='application/json')
    key_present = bool(os.environ.get('FPL_DEEPSEEK_API_KEY'))
    use_llm = os.environ.get('FPL_USE_LLM') == '1'
    return JsonResponse({
        'fpl_deepseek_api_key_present': key_present,
        'fpl_use_llm': use_llm,
        'deepseek_url': os.environ.get('FPL_DEEPSEEK_API_URL', '')
    })


@csrf_exempt
def upload_view(request):
    # Diagnostic endpoint to verify form POSTs reach this view
    try:
        print('VIEW REACHED')
    except Exception:
        pass

    if request.method == 'POST':
        try:
            print('POST DETECTED')
        except Exception:
            pass
        try:
            print('FILES:', dict(request.FILES))
        except Exception:
            pass

        uploaded_file = request.FILES.get('flight_plan')
        if not uploaded_file:
            return HttpResponse('No file received')
        return HttpResponse('File received successfully')

    return HttpResponse('Upload page (GET)')


@csrf_exempt
def submit_analysis(request):
    """Accepts form POST with field 'payload' (JSON string). Returns an HTML page that sets sessionStorage['fplguru_payload'] and redirects to the analysis page.

    This avoids server-side session handling while ensuring the analysis page receives the full JSON payload im