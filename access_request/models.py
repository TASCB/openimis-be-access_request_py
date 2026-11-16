"""Access request/account provisioning models."""
import secrets
import uuid

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from core.models import HistoryModel, UUIDModel, ObjectMutation, MutationLog
from location.models import Location


def generate_reference_code():
    """Short, opaque, human-shareable code the applicant uses to check status."""
    return 'AR-' + secrets.token_hex(4).upper()


class RequestType(models.TextChoices):
    NEW = 'NEW', _('New user Creation')
    ACTIVATE = 'ACTIVATE', _('Activation of Existing user')


class UserCategory(models.TextChoices):
    TASAF_STAFF = 'TASAF_STAFF', _('TASAF Staff')      # HQ staff, no location
    PAA_STAFF = 'PAA_STAFF', _('PAA Staff')            # placed in the location hierarchy
    OTHER = 'OTHER', _('Other')                        # external, org + job title


class AdministrativeLevel(models.TextChoices):
    """Depth of the location the applicant is scoped to (PAA staff only)."""
    PAA = 'PAA', _('PAA')                              # Region + District
    VILLAGE = 'VILLAGE', _('Village')                 # Region + District + Ward + Village


class RequestStatus(models.TextChoices):
    SUBMITTED = 'SUBMITTED', _('Submitted')
    MANAGER_APPROVED = 'MANAGER_APPROVED', _('Manager Approved')
    ICT_APPROVED = 'ICT_APPROVED', _('ICT Approved')
    PROVISIONED = 'PROVISIONED', _('Account Provisioned')
    REJECTED = 'REJECTED', _('Rejected')
    FAILED = 'FAILED', _('Provisioning Failed')


TERMINAL_STATUSES = (RequestStatus.PROVISIONED, RequestStatus.REJECTED)


class AccessProfile(HistoryModel):
    """A friendly, config-driven access label shown on the public form.

    Holds the *suggested* core Role id(s) and default scope; these only pre-fill the
    approver's choice — the real Role(s) are confirmed by staff at approval time.
    """
    code = models.CharField(max_length=255, blank=False, null=False)
    name = models.CharField(max_length=255, blank=False, null=False)
    description = models.TextField(blank=True, null=True)
    # Suggested core.Role ids are confirmed or overridden during approval.
    suggested_role_ids = models.JSONField(default=list, blank=True)
    # The form lists the title only under this section; empty = every section.
    section_group = models.ForeignKey(
        'auth.Group', on_delete=models.SET_NULL, blank=True, null=True, related_name='access_profiles')
    unit = models.ForeignKey(
        'AccessUnit', on_delete=models.SET_NULL, blank=True, null=True, related_name='profiles')
    default_location = models.ForeignKey(
        Location, on_delete=models.DO_NOTHING, blank=True, null=True,
        related_name='access_profiles')
    is_active = models.BooleanField(default=True)

    class Meta:
        indexes = [
            models.Index(fields=['code']),
            models.Index(fields=['is_active']),
        ]

    def __str__(self):
        return f'{self.name} ({self.code})'


class AccessUnit(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=32, unique=True)
    name = models.CharField(max_length=255)
    section_group = models.ForeignKey('auth.Group', on_delete=models.CASCADE, related_name='access_units')
    group = models.OneToOneField('auth.Group', on_delete=models.PROTECT, related_name='access_unit')
    head_profile = models.ForeignKey(
        'AccessProfile', on_delete=models.SET_NULL, blank=True, null=True, related_name='headed_units')
    reports_to = models.ForeignKey(
        'self', on_delete=models.SET_NULL, blank=True, null=True, related_name='child_units')
    sort_order = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ('sort_order', 'name')

    def __str__(self):
        return f'{self.name} ({self.code})'


class SectionSponsor(models.Model):
    """Which role signs the MANAGER step for applications from a section.

    Without a row the step falls back to "any holder of the manager-approve right".
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    section_group = models.OneToOneField(
        'auth.Group', on_delete=models.CASCADE, related_name='access_sponsor')
    sponsor_role = models.ForeignKey('core.Role', on_delete=models.DO_NOTHING, related_name='+')
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f'{self.section_group} → {self.sponsor_role}'


class AccessRequest(HistoryModel):
    """A public account application / activation request."""
    reference_code = models.CharField(
        max_length=32, unique=True, default=generate_reference_code, editable=False)
    request_type = models.CharField(
        max_length=20, choices=RequestType.choices, default=RequestType.NEW)

    full_name = models.CharField(max_length=255, blank=False, null=False)
    organization_paa = models.CharField(max_length=255, blank=True, null=True)
    section = models.CharField(max_length=255, blank=True, null=True)  # label snapshot of section_group
    designation = models.CharField(max_length=255, blank=True, null=True)
    email = models.CharField(max_length=255, blank=False, null=False)
    phone = models.CharField(max_length=50, blank=True, null=True)
    applicant_signature = models.TextField(blank=True, null=True)

    section_group = models.ForeignKey(
        'auth.Group', on_delete=models.DO_NOTHING, blank=True, null=True,
        related_name='access_requests')
    unit = models.ForeignKey(
        AccessUnit, on_delete=models.DO_NOTHING, blank=True, null=True, related_name='requests')
    unit_name = models.CharField(max_length=255, blank=True, null=True)
    approver_group = models.ForeignKey(
        'auth.Group', on_delete=models.DO_NOTHING, blank=True, null=True, related_name='+')

    user_category = models.CharField(
        max_length=20, choices=UserCategory.choices, blank=True, null=True)
    # Only for PAA staff; decides how deep `requested_location` is captured.
    administrative_level = models.CharField(
        max_length=20, choices=AdministrativeLevel.choices, blank=True, null=True)

    profile = models.ForeignKey(
        AccessProfile, on_delete=models.DO_NOTHING, blank=True, null=True,
        related_name='requests')
    requested_location = models.ForeignKey(
        Location, on_delete=models.DO_NOTHING, blank=True, null=True,
        related_name='access_requests')

    status = models.CharField(
        max_length=20, choices=RequestStatus.choices, default=RequestStatus.SUBMITTED)
    rejection_reason = models.TextField(blank=True, null=True)

    created_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.DO_NOTHING, blank=True, null=True,
        related_name='access_requests')
    assigned_username = models.CharField(max_length=8, blank=True, null=True)
    provisioning_error = models.TextField(blank=True, null=True)

    class Meta:
        indexes = [
            models.Index(fields=['reference_code']),
            models.Index(fields=['status']),
            models.Index(fields=['email']),
            models.Index(fields=['request_type']),
        ]

    def __str__(self):
        return f'{self.reference_code} — {self.full_name} [{self.status}]'


class AccessProfileMutation(UUIDModel, ObjectMutation):
    access_profile = models.ForeignKey(AccessProfile, models.DO_NOTHING, related_name='mutations')
    mutation = models.ForeignKey(MutationLog, models.DO_NOTHING, related_name='access_profiles')


class AccessRequestMutation(UUIDModel, ObjectMutation):
    access_request = models.ForeignKey(AccessRequest, models.DO_NOTHING, related_name='mutations')
    mutation = models.ForeignKey(MutationLog, models.DO_NOTHING, related_name='access_requests')


class AuthSession(models.Model):
    """One signed-in browser: a sign-in and the token refreshes that follow it.

    openIMIS tokens are stateless JWTs. A refresh keeps the sign-in's `origIat`, so a user and that
    timestamp name one session for its whole life. A row is recorded the first time a token is seen
    (see `auth_sessions`), and an ended row makes every token of that session refused from then on.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey('core.User', on_delete=models.CASCADE, related_name='+')
    # The sign-in time as the token carries it (`origIat`, seconds since the epoch).
    orig_iat = models.BigIntegerField()
    user_agent = models.TextField(blank=True, default='')
    ip_address = models.CharField(max_length=45, blank=True, default='')
    # A fingerprint of the user's signing key when the session began: a password change replaces the
    # key, which silently ends every session signed with the old one.
    key_hint = models.CharField(max_length=16, blank=True, default='')
    last_seen_at = models.DateTimeField()
    ended_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['user', 'orig_iat'], name='access_auth_session_unique'),
        ]

    def __str__(self):
        return f'{self.user_id} @ {self.orig_iat}{" (ended)" if self.ended_at else ""}'
