"""Service layer for the Access Request / Account Provisioning module.

- ``AccessProfileService`` — CRUD for curated profiles (``core.services.BaseService``).
- ``AccessRequestService`` — the workflow chokepoint: public ``submit`` (which hands the
  two-level Manager→ICT sign-off to the generic Approval Engine, flow
  ``ACCESS_REQUEST_ACCOUNT``) and ``provision`` (which, once the engine's adapter has set the
  request to ``ICT_APPROVED``, calls into ``core`` to create/reactivate the interactive user and
  email a set-password link). Approvals live entirely in the engine's
  ApprovalRequest/Step/Decision rows and surface in the standard Tasks inbox — this module no
  longer keeps its own approval table.

Privilege guardrail: ``provision`` only grants the role ids the approver explicitly
confirms, and ``_assert_can_grant`` rejects any role the approver does not themselves
hold — the public "profile" is only a suggestion.
"""
import logging
from datetime import datetime

from django.contrib.auth.models import Group
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from core.services import BaseService
from core.services.utils import output_exception, model_representation, check_authentication
from core.signals import register_service_signal
from core.models import User, InteractiveUser
from core.services import userServices

from access_request.apps import AccessRequestConfig
from access_request.models import (
    AccessProfile, AccessRequest, RequestType, RequestStatus, generate_reference_code,
)
from access_request.validations import (
    AccessProfileValidation, AccessRequestValidation,
)

logger = logging.getLogger(__name__)

SYSTEM_AUDIT_USER_ID = 1  # used for public (unauthenticated) submissions


# ---------------------------------------------------------------------------
# Curated profile CRUD
# ---------------------------------------------------------------------------
class AccessProfileService(BaseService):
    OBJECT_TYPE = AccessProfile

    def __init__(self, user, validation_class=AccessProfileValidation):
        super().__init__(user, validation_class)

    @register_service_signal('access_profile_service.create')
    def create(self, obj_data):
        return super().create(obj_data)

    @register_service_signal('access_profile_service.update')
    def update(self, obj_data):
        return super().update(obj_data)

    @register_service_signal('access_profile_service.delete')
    def delete(self, obj_data):
        return super().delete(obj_data)


# ---------------------------------------------------------------------------
# Access request workflow
# ---------------------------------------------------------------------------
class AccessRequestService:
    """Standalone workflow service (not BaseService CRUD — the public submit path has
    no authenticated user, and the approval transitions are bespoke)."""

    def __init__(self, user=None):
        self.user = user

    # -- public submission -------------------------------------------------
    @register_service_signal('access_request_service.submit')
    def submit(self, payload):
        """Create an inert request from the *untrusted* public form.

        ``payload`` keys: request_type, full_name, organization_paa, section,
        section_group_id (auth.Group id), designation, email, phone, applicant_signature,
        user_category, administrative_level, profile_id (uuid), requested_location_id (int)."""
        try:
            with transaction.atomic():
                profile = None
                if payload.get('profile_id'):
                    profile = AccessProfile.objects.filter(
                        id=payload['profile_id'], is_active=True, is_deleted=False).first()

                # Resolve the Section user-group and snapshot its name as the label.
                section_group_id = payload.get('section_group_id') or None
                section_label = payload.get('section')
                if section_group_id:
                    grp = Group.objects.filter(id=section_group_id).first()
                    if grp:
                        section_label = grp.name
                    else:
                        section_group_id = None

                req = AccessRequest(
                    reference_code=generate_reference_code(),
                    request_type=payload.get('request_type') or RequestType.NEW,
                    full_name=(payload.get('full_name') or '').strip(),
                    organization_paa=payload.get('organization_paa'),
                    section=section_label,
                    section_group_id=section_group_id,
                    designation=payload.get('designation'),
                    email=(payload.get('email') or '').strip(),
                    phone=(payload.get('phone') or '').strip(),
                    applicant_signature=payload.get('applicant_signature'),
                    user_category=payload.get('user_category') or None,
                    administrative_level=payload.get('administrative_level') or None,
                    profile=profile,
                    requested_location_id=payload.get('requested_location_id'),
                    status=RequestStatus.SUBMITTED,
                )
                # Public submit has no logged-in user → record it against the system core user
                # (HistoryModel.save needs a real user, not just an audit id).
                system_user = self.user if getattr(self.user, 'username', None) else self._system_core_user()
                if not system_user:
                    raise RuntimeError(_("No system user available to record the request"))
                req.save(user=system_user)

                # The two-level Manager→ICT sign-off is owned entirely by the generic Approval
                # Engine (flow ACCESS_REQUEST_ACCOUNT). It creates the steps + the Tasks inbox and,
                # on final approval, its adapter sets this request to ICT_APPROVED (ready to
                # provision). There is no legacy in-module approval path.
                if not self._start_engine_approval(req):
                    raise RuntimeError(_("Approval engine could not start the request"))

                return {"success": True, "reference_code": req.reference_code,
                        "data": model_representation(req)}
        except Exception as exc:
            return output_exception(model_name='AccessRequest', method='submit', exception=exc)

    # -- provisioning (after the engine reaches ICT_APPROVED) --------------
    @register_service_signal('access_request_service.provision')
    def provision(self, request_id, role_ids, username, district_ids=None):
        """Create (or reactivate) the core interactive user and email a set-password
        link.  ``role_ids`` are the approver-CONFIRMED core Role ids.

        This, not the approval finalising, is the moment the account exists."""
        try:
            check_authentication(self.user)
            if not self.user.has_perms(AccessRequestConfig.gql_ict_approve_perms):
                raise PermissionError(_("unauthorized"))
            self._assert_can_grant(role_ids)

            with transaction.atomic():
                req = AccessRequest.objects.select_for_update().filter(
                    id=request_id, is_deleted=False).first()
                if not req:
                    return {"success": False, "message": _("Request not found")}
                if req.status != RequestStatus.ICT_APPROVED:
                    return {"success": False, "message": _("Request is not ICT-approved")}
                if not role_ids:
                    return {"success": False, "message": _("At least one role must be confirmed")}

                username = (username or '').strip()[:8]  # core caps login_name at 8
                other_names, last_name = self._split_name(req.full_name)
                data = {
                    'username': username,
                    'other_names': other_names,
                    'last_name': last_name,
                    'phone': req.phone,
                    'email': req.email,
                    'language': AccessRequestConfig.default_user_language,
                    'roles': list(role_ids),
                }
                if district_ids:
                    data['districts'] = list(district_ids)

                audit_id = self._audit_id()
                # NEW → create; ACTIVATE → resolve existing by username, else create.
                existing_user_id = None
                if req.request_type == RequestType.ACTIVATE:
                    existing = User.objects.filter(username=username).first()
                    existing_user_id = existing.id if existing else None

                i_user, _created = userServices.create_or_update_interactive_user(
                    user_id=existing_user_id, data=data, audit_user_id=audit_id, connected=False)
                user, _c = userServices.create_or_update_core_user(
                    user_uuid=existing_user_id, username=username, i_user=i_user)

                req.created_user = user
                req.assigned_username = username
                req.status = RequestStatus.PROVISIONED
                req.save(username=getattr(self.user, 'username', None))

                # Footer note: "Username approved, password shared via email."
                self._send_credentials(req, username)
                return {"success": True, "username": username,
                        "data": model_representation(req)}
        except Exception as exc:
            # mark FAILED so staff can retry, but surface the error
            try:
                AccessRequest.objects.filter(id=request_id).update(
                    status=RequestStatus.FAILED, provisioning_error=str(exc))
            except Exception:
                pass
            return output_exception(model_name='AccessRequest', method='provision', exception=exc)

    # -- helpers -----------------------------------------------------------
    def _audit_id(self):
        return getattr(self.user, 'id_for_audit', None) or getattr(self.user, 'id', None) or SYSTEM_AUDIT_USER_ID

    @staticmethod
    def _split_name(full_name):
        parts = (full_name or '').strip().split()
        if not parts:
            return '', ''
        if len(parts) == 1:
            return parts[0], parts[0]
        return ' '.join(parts[:-1]), parts[-1]

    def _assert_can_grant(self, role_ids):
        """An approver may only grant roles at/below their own authority: reject any
        role id the approver does not themselves hold (unless they're a super-admin)."""
        if getattr(self.user, 'is_imis_admin', False) or getattr(self.user, 'is_superuser', False):
            return
        i_user = getattr(self.user, 'i_user', None)
        held = set()
        if i_user:
            from core.models import UserRole
            held = set(UserRole.objects.filter(
                user=i_user, validity_to__isnull=True).values_list('role_id', flat=True))
        forbidden = [r for r in (role_ids or []) if r not in held]
        if forbidden:
            raise PermissionError(
                _("You may not grant roles you do not hold: %(roles)s") % {"roles": forbidden})

    def _send_credentials(self, req, username):
        try:
            if AccessRequestConfig.credential_delivery == 'SET_PASSWORD_LINK':
                # emails a tokenized /set_password link; no plaintext secret is stored
                userServices.reset_user_password(request=None, username=username)
        except Exception as exc:
            logger.warning("access_request: credential email failed for %s (%s)", username, exc)

    def _notify_rejected(self, req):
        # Placeholder — wire an email template ("your request was not approved").
        logger.info("access_request %s rejected", req.reference_code)

    def _system_core_user(self):
        """The conventional system/Admin core.User (audit id 1), used as the requester for a
        public (unauthenticated) submission routed through the approval engine."""
        return User.objects.filter(
            i_user_id=SYSTEM_AUDIT_USER_ID, validity_to__isnull=True).first()

    def _start_engine_approval(self, req):
        """Route the two-level sign-off through the generic Approval Engine. Returns True if the
        engine took ownership; False to fall back to the legacy slots (rollback-safe)."""
        try:
            from approval.services import ApprovalService
        except Exception as exc:
            logger.warning("access_request: approval engine unavailable (%s) — legacy path", exc)
            return False
        executor = self.user if getattr(self.user, 'username', None) else self._system_core_user()
        if not executor:
            logger.warning("access_request: no system user for approval engine — legacy path")
            return False
        summary = {
            'reference_code': req.reference_code, 'full_name': req.full_name, 'email': req.email,
            'designation': req.designation, 'organization_paa': req.organization_paa,
            'profile': req.profile.name if req.profile else None,
            'request_type': req.request_type,
        }
        res = ApprovalService(executor).request_approval(req, 'ACCESS_REQUEST_ACCOUNT', summary=summary)
        if not res.get('success'):
            logger.warning("access_request: engine request_approval failed (%s) — legacy path", res)
            return False
        return True
