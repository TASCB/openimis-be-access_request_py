"""Public (unauthenticated) DRF endpoints for the Access Request module.

The landing page is served to people who do NOT have a login, so submission cannot
go through GraphQL (which requires auth).  These endpoints are ``AllowAny`` with
empty ``authentication_classes`` and are hardened with a per-IP rate limit + honeypot
(+ pluggable CAPTCHA) — mirroring the Training QR self check-in.  They only *record*
an inert ``AccessRequest``; nothing is granted until two staff approve.

Endpoints:
  GET  /api/access_request/profiles/            → active curated profiles (for the form)
  POST /api/access_request/submit/              → create a request
  GET  /api/access_request/status/<ref_code>/   → coarse status by reference code
"""
import logging

from django.core.cache import cache
from rest_framework import views
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from access_request.apps import AccessRequestConfig
from access_request.models import AccessProfile, AccessRequest, RequestType
from access_request.services import AccessRequestService

logger = logging.getLogger(__name__)

# Coarse status labels exposed publicly (never leak approver identities / comments).
PUBLIC_STATUS = {
    'SUBMITTED': 'received',
    'MANAGER_APPROVED': 'in_review',
    'ICT_APPROVED': 'in_review',
    'PROVISIONED': 'approved',
    'REJECTED': 'not_approved',
    'FAILED': 'in_review',
}


def _passes_captcha(data):
    # Placeholder — wire a provider (Turnstile/hCaptcha) here and flip
    # AccessRequestConfig.captcha_enabled. For now anti-bot relies on the honeypot +
    # per-IP rate limit.
    if not AccessRequestConfig.captcha_enabled:
        return True
    return bool((data.get('captcha_token') or '').strip())


class AccessProfileListView(views.APIView):
    """Public list of ACTIVE curated profiles for the application form."""
    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request):
        if not AccessRequestConfig.public_submit_enabled:
            return Response({'error': 'disabled'}, status=403)
        profiles = AccessProfile.objects.filter(is_active=True, is_deleted=False).order_by('name')
        return Response({'profiles': [
            {'uuid': str(p.id), 'code': p.code, 'name': p.name, 'description': p.description}
            for p in profiles
        ]})


class AccessRequestSubmitView(views.APIView):
    """Public account application / activation submission."""
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        if not AccessRequestConfig.public_submit_enabled:
            return Response({'error': 'disabled'}, status=403)

        ip = request.META.get('REMOTE_ADDR', 'anon')
        key = f'access_request:submit:rl:{ip}'
        count = cache.get(key, 0)
        if count >= AccessRequestConfig.submit_rate_max:
            return Response({'error': 'rate_limited'}, status=429)
        cache.set(key, count + 1, AccessRequestConfig.submit_rate_window)

        data = request.data
        if (data.get('hp') or '').strip():          # honeypot — silently accept bots
            return Response({'ok': True})
        if not _passes_captcha(data):
            return Response({'error': 'captcha'}, status=400)

        full_name = (data.get('full_name') or '').strip()
        email = (data.get('email') or '').strip()
        missing = [f for f, v in (('full_name', full_name), ('email', email)) if not v]
        if missing:
            return Response({'error': 'missing_fields', 'fields': missing}, status=400)

        request_type = data.get('request_type')
        if request_type not in dict(RequestType.choices):
            request_type = RequestType.NEW

        payload = {
            'request_type': request_type,
            'full_name': full_name,
            'organization_paa': data.get('organization_paa'),
            'section': data.get('section'),
            'designation': data.get('designation'),
            'email': email,
            'phone': data.get('phone'),
            'applicant_signature': data.get('applicant_signature'),
            'profile_id': data.get('profile_id'),
            'requested_location_id': data.get('requested_location_id'),
        }
        res = AccessRequestService().submit(payload)
        if not res.get('success'):
            # Do NOT echo internal errors to the public client.
            logger.warning("access_request submit failed: %s", res.get('message'))
            return Response({'error': 'submit_failed'}, status=400)
        return Response({'ok': True, 'reference_code': res['reference_code']})


class AccessRequestStatusView(views.APIView):
    """Coarse status lookup by reference code (no PII, no approver detail)."""
    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request, ref_code):
        req = AccessRequest.objects.filter(
            reference_code=ref_code, is_deleted=False).only('status').first()
        if not req:
            return Response({'error': 'not_found'}, status=404)
        return Response({'status': PUBLIC_STATUS.get(req.status, 'in_review')})
