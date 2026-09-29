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
                return

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
        except Exception as exc:
            logger.error("access_request approval adapter failed", exc_info=exc)
            return [str(exc)]
