"""Public (unauthenticated) DRF endpoints for the Access Request module.

The landing page is served to people who do NOT have a login, so submission cannot
go through GraphQL (which requires auth).  These endpoints are ``AllowAny`` with
empty ``authentication_classes`` and are hardened with a per-IP rate limit + honeypot
(+ pluggable CAPTCHA) — mirroring the Training QR self check-in.  They only *record*
an inert ``AccessRequest``; nothing is granted until two staff approve.

Endpoints:
  GET  /api/access_request/profiles/            → active curated profiles (for the form)
  GET  /api/access_request/sections/            → active User Groups (auth.Group) for the Section dropdown
  GET  /api/access_request/locations/?parent=   → children of a location (roots when absent) for cascading pickers
  POST /api/access_request/submit/              → create a request
  GET  /api/access_request/status/<ref_code>/   → coarse status by reference code
"""
import logging
import re

from django.contrib.auth.models import Group
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from rest_framework import views
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from location.models import Location

from access_request.apps import AccessRequestConfig
from access_request.models import (
    AccessProfile, AccessRequest, RequestType, UserCategory, AdministrativeLevel,
    TERMINAL_STATUSES,
)
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


# Tanzanian numbers: 9 national digits after 0 / 255 — mobile 6x/7x, landline 2x.
_PHONE_NATIONAL_RE = re.compile(r'^[267]\d{8}$')

# Mirror the model column sizes so an over-long value is a field error, not a DB error.
_MAX_LENGTHS = {'full_name': 255, 'email': 254, 'phone': 50, 'organization_paa': 255, 'designation': 255}


def normalize_phone(raw):
    """Return the number as +255XXXXXXXXX, or None when it is not a Tanzanian number."""
    digits = re.sub(r'[\s\-().]', '', raw or '')
    if digits.startswith('+'):
        digits = digits[1:]
        if not digits.startswith('255'):
            return None
    if digits.startswith('255'):
        digits = digits[3:]
    elif digits.startswith('0'):
        digits = digits[1:]
    return f'+255{digits}' if _PHONE_NATIONAL_RE.match(digits) else None


def client_ip(request):
    """The applicant's IP for rate limiting: nginx sets X-Real-IP; REMOTE_ADDR alone would be
    the nginx address once the frontend container gets a new IP."""
    return request.META.get('HTTP_X_REAL_IP') or request.META.get('REMOTE_ADDR') or 'anon'


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


class SectionListView(views.APIView):
    """Public list of openIMIS User Groups (django ``auth.Group``) for the Section dropdown.

    Only the id (stored) + name (shown) are exposed — no membership or other detail. This is the
    same ``auth.Group`` set openIMIS uses for ``auto_provisioning_user_group``; seeded from the
    TASAF RBAC user groups (UG01–UG08)."""
    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request):
        if not AccessRequestConfig.public_submit_enabled:
            return Response({'error': 'disabled'}, status=403)
        groups = Group.objects.order_by('name')
        return Response({'sections': [{'id': g.id, 'name': g.name} for g in groups]})


class LocationListView(views.APIView):
    """Public, cascading location lookup for the administrative-location pickers.

    Returns the children of the ``parent`` location (or the top-level roots when ``parent`` is
    absent), reading the configured ``Location`` hierarchy + type straight from the DB. Because it
    walks ``parent``/``type`` rather than assuming a fixed depth, it serves BOTH the Mainland
    Region→District→Ward→Village chain and the Zanzibar (Unguja/Pemba PAA) structure with no
    special-case logic — exactly the hierarchy configured in openIMIS / api-etl."""
    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request):
        if not AccessRequestConfig.public_submit_enabled:
            return Response({'error': 'disabled'}, status=403)
        qs = Location.objects.filter(validity_to__isnull=True)
        parent = request.GET.get('parent')
        if parent:
            qs = qs.filter(parent_id=parent)
        else:
            qs = qs.filter(parent__isnull=True)   # roots (type-agnostic — respects config)
        qs = qs.order_by('name')
        return Response({'locations': [
            {'id': loc.id, 'name': loc.name, 'type': loc.type} for loc in qs
        ]})


class AccessRequestSubmitView(views.APIView):
    """Public account application / activation submission."""
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        if not AccessRequestConfig.public_submit_enabled:
            return Response({'error': 'disabled'}, status=403)

        key = f'access_request:submit:rl:{client_ip(request)}'
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

        # Conditional requirements mirror the form: only validate what the category shows.
        category = data.get('user_category')
        if category not in dict(UserCategory.choices):
            category = None
        admin_level = data.get('administrative_level')
        if admin_level not in dict(AdministrativeLevel.choices):
            admin_level = None

        if not (data.get('section_group_id') or data.get('section')):
            missing.append('section')
        if category == UserCategory.PAA_STAFF:
            if not admin_level:
                missing.append('administrative_level')
            # Region + District always required for PAA staff; Ward + Village add depth for Village.
            if not data.get('requested_location_id'):
                missing.append('location')
        elif category == UserCategory.OTHER:
            if not (data.get('organization_paa') or '').strip():
                missing.append('organization_paa')
            if not (data.get('designation') or '').strip():
                missing.append('designation')

        if missing:
            return Response({'error': 'missing_fields', 'fields': missing}, status=400)

        invalid = {}
        for field, limit in _MAX_LENGTHS.items():
            if len(str(data.get(field) or '').strip()) > limit:
                invalid[field] = 'too_long'
        if 'email' not in invalid:
            try:
                validate_email(email)
            except ValidationError:
                invalid['email'] = 'invalid'
        phone = str(data.get('phone') or '').strip()
        if phone and 'phone' not in invalid:
            phone = normalize_phone(phone)
            if not phone:
                invalid['phone'] = 'invalid'
        if invalid:
            return Response({'error': 'invalid_fields', 'fields': invalid}, status=400)

        # One open application per email: a resubmission would otherwise start a second
        # Manager→ICT approval for the same person.
        if AccessRequest.objects.filter(email__iexact=email, is_deleted=False) \
                .exclude(status__in=TERMINAL_STATUSES).exists():
            return Response({'error': 'duplicate_request', 'fields': {'email': 'duplicate'}}, status=409)

        request_type = data.get('request_type')
        if request_type not in dict(RequestType.choices):
            request_type = RequestType.NEW

        payload = {
            'request_type': request_type,
            'full_name': full_name,
            'organization_paa': data.get('organization_paa'),
            'section': data.get('section'),
            'section_group_id': data.get('section_group_id'),
            'designation': data.get('designation'),
            'email': email,
            'phone': phone or None,
            'applicant_signature': data.get('applicant_signature'),
            'user_category': category,
            'administrative_level': admin_level,
            # Coerce empty strings to None: the form posts '' for these id fields when the
            # category hides them (TASAF_STAFF / OTHER send no location), and '' breaks the
            # integer/uuid FK columns on save.
            'profile_id': data.get('profile_id') or None,
            'requested_location_id': data.get('requested_location_id') or None,
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
