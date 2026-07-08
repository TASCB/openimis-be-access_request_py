"""Service-signal bindings for access_request.

Binds the domain adapter to the generic Approval Engine's terminal hook. This is the OpenIMIS-native
cross-module pattern (same as payment_cycle binding to ``task_service.complete_task``) — the approval
engine never imports access_request; access_request binds itself to the engine's outcome.
"""
import logging

logger = logging.getLogger(__name__)


def bind_service_signals():
    try:
        from core.service_signals import ServiceSignalBindType
        from core.signals import bind_service_signal
        from access_request.approval_adapter import AccessRequestApprovalAdapter
        bind_service_signal(
            'approval_service.finalized',
            AccessRequestApprovalAdapter.on_finalized,
            bind_type=ServiceSignalBindType.AFTER,
        )
    except Exception as exc:
        # approval module may be absent in some deployments — degrade gracefully.
        logger.warning("access_request: approval-engine binding skipped (%s)", exc)
