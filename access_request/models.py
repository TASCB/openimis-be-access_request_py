"""Access request/account provisioning models."""
import secrets

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

    # Section = an openIMIS User Group (django auth.Group); the id is the identifier stored,
    # the name is what the applicant sees. `section` above keeps a denormalised label snapshot.
    section_group = models.ForeignKey(
        'auth.Group', on_delete=models.DO_NOTHING, blank=True, null=True,
        related_name='access_requests')

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
