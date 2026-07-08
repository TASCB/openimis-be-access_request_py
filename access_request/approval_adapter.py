"""Domain adapter: consumes the generic Approval Engine's terminal outcome.

Bound to the ``approval_service.finalized`` service signal (see ``signals``). The engine owns the
two-level sign-off (Manager → ICT); this adapter mirrors the terminal outcome back onto the
``AccessRequest`` so the existing provisioning action and the public status page keep working:

- APPROVED (both steps signed)  -> ``AccessRequest.status = ICT_APPROVED`` (ready to provision).
  Provisioning stays a SEPARATE explicit action because it mints a core user and needs the approver
  to confirm role ids / username — the engine does not capture those.
- REJECTED                       -> ``AccessRequest.status = REJECTED`` + reject notification.
- CANCELLED                      -> left as-is (no cancelled status); the ApprovalRequest is the record.

The mirror uses ``.update()`` (no audit user needed) because the authoritative audit trail lives in
the engine's ApprovalRequest/Step/Decision rows; ``AccessRequest.status`` is a denormalised mirror.
"""
import logging

logger = logging.getLogger(__name__)

DOMAIN = 'access_request.AccessRequest'


class AccessRequestApprovalAdapter:

    @staticmethod
    def on_finalized(**kwargs):
        try:
            result = kwargs.get('result') or {}
            data = result.get('data') or {}
            if data.get('domain') != DOMAIN:
                return  # another domain's request — ignore

            from approval.models import ApprovalRequest
            from access_request.models import AccessRequest, RequestStatus
            from access_request.services import AccessRequestService

            appr = ApprovalRequest.objects.filter(id=data.get('id')).first()
            if not appr:
                return
            ar = AccessRequest.objects.filter(id=appr.object_id, is_deleted=False).first()
            if not ar:
                logger.warning("access_request adapter: AccessRequest %s not found", appr.object_id)
                return

            decision = data.get('decision')
            if decision == 'APPROVED':
                AccessRequest.objects.filter(id=ar.id).update(status=RequestStatus.ICT_APPROVED)
                logger.info("access_request %s -> ICT_APPROVED via approval engine", ar.reference_code)
            elif decision == 'REJECTED':
                AccessRequest.objects.filter(id=ar.id).update(status=RequestStatus.REJECTED)
                AccessRequestService(None)._notify_rejected(ar)
                logger.info("access_request %s -> REJECTED via approval engine", ar.reference_code)
            # CANCELLED: no cancelled status on AccessRequest — leave it; engine holds the record.
        except Exception as exc:
            logger.error("access_request approval adapter failed", exc_info=exc)
            return [str(exc)]
