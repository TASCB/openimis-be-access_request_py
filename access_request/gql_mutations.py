"""GraphQL mutations for the Access Request module.

- ``AccessProfile`` CRUD follows the openIMIS ``BaseHistoryModel*MutationMixin +
  BaseMutation`` pattern, journaling through ``AccessProfileMutation``.
- The workflow mutations (``ManagerApprove/Reject``, ``IctApprove/Reject``,
  ``ProvisionAccessRequest``) are bespoke ``BaseMutation`` subclasses delegating to
  ``AccessRequestService``.

Public *submission* is NOT a GraphQL mutation — it comes in through the
unauthenticated DRF endpoint in ``views.py`` (see ``docs/00-overview.md`` §8).
"""
import graphene
from django.core.exceptions import PermissionDenied
from django.utils.translation import gettext as _

from core.gql.gql_mutations.base_mutation import (
    BaseHistoryModelCreateMutationMixin, BaseHistoryModelUpdateMutationMixin,
    BaseHistoryModelDeleteMutationMixin, BaseMutation,
)
from core.schema import OpenIMISMutation

from access_request.apps import AccessRequestConfig
from access_request.models import (
    AccessProfile, AccessProfileMutation, RequestType,
)
from access_request.services import AccessProfileService, AccessRequestService


def _strip_client(data):
    data.pop('client_mutation_id', None)
    data.pop('client_mutation_label', None)


def _journal(mutation_model, fk_name, user, client_mutation_id, obj):
    if client_mutation_id and obj is not None:
        mutation_model.object_mutated(user, client_mutation_id=client_mutation_id, **{fk_name: obj})


RequestTypeEnum = graphene.Enum('AccessRequestTypeInput', [(c.value, c.value) for c in RequestType])


# ===========================================================================
# AccessProfile CRUD (curated profiles + profile→role mapping)
# ===========================================================================
class CreateAccessProfileInput(OpenIMISMutation.Input):
    code = graphene.String(required=True)
    name = graphene.String(required=True)
    description = graphene.String(required=False)
    suggested_role_ids = graphene.List(graphene.Int, required=False)
    default_location_id = graphene.Int(required=False)
    is_active = graphene.Boolean(required=False)


class CreateAccessProfileMutation(BaseHistoryModelCreateMutationMixin, BaseMutation):
    _mutation_module = "access_request"
    _mutation_class = "CreateAccessProfileMutation"

    @classmethod
    def _validate_mutation(cls, user, **data):
        super()._validate_mutation(user, **data)
        if not user.has_perms(AccessRequestConfig.gql_profile_manage_perms):
            raise PermissionDenied(_("unauthorized"))

    @classmethod
    def _mutate(cls, user, **data):
        client_mutation_id = data.get('client_mutation_id')
        _strip_client(data)
        res = AccessProfileService(user).create(data)
        if res['success']:
            obj = AccessProfile.objects.get(id=res['data']['id'])
            _journal(AccessProfileMutation, 'access_profile', user, client_mutation_id, obj)
        return res if not res['success'] else None

    class Input(CreateAccessProfileInput):
        pass


class UpdateAccessProfileMutation(BaseHistoryModelUpdateMutationMixin, BaseMutation):
    _mutation_module = "access_request"
    _mutation_class = "UpdateAccessProfileMutation"
    _model = AccessProfile

    @classmethod
    def _validate_mutation(cls, user, **data):
        super()._validate_mutation(user, **data)
        if not user.has_perms(AccessRequestConfig.gql_profile_manage_perms):
            raise PermissionDenied(_("unauthorized"))

    @classmethod
    def _mutate(cls, user, **data):
        client_mutation_id = data.get('client_mutation_id')
        _strip_client(data)
        res = AccessProfileService(user).update(data)
        if res['success']:
            obj = AccessProfile.objects.get(id=data['id'])
            _journal(AccessProfileMutation, 'access_profile', user, client_mutation_id, obj)
        return res if not res['success'] else None

    class Input(CreateAccessProfileInput):
        id = graphene.UUID(required=True)


class DeleteAccessProfileMutation(BaseHistoryModelDeleteMutationMixin, BaseMutation):
    _mutation_module = "access_request"
    _mutation_class = "DeleteAccessProfileMutation"
    _model = AccessProfile

    @classmethod
    def _validate_mutation(cls, user, **data):
        super()._validate_mutation(user, **data)
        if not user.has_perms(AccessRequestConfig.gql_profile_manage_perms):
            raise PermissionDenied(_("unauthorized"))

    @classmethod
    def _mutate(cls, user, **data):
        _strip_client(data)
        service = AccessProfileService(user)
        for identifier in data.get('ids', []):
            res = service.delete({'id': identifier})
            if not res['success']:
                return res
        return None

    class Input(OpenIMISMutation.Input):
        ids = graphene.List(graphene.UUID)


# ===========================================================================
# Workflow: provisioning (the Manager→ICT sign-off is owned by the Approval Engine —
# approve/reject via approveApprovalStep / the Tasks inbox, not this module).
# ===========================================================================
class ProvisionAccessRequestMutation(BaseMutation):
    """Create/reactivate the core user with the CONFIRMED roles + email credentials.

    Gated on ``AccessRequest.status == ICT_APPROVED`` — the state the Approval Engine's
    ``approval_service.finalized`` adapter sets once both sign-off steps are approved."""
    _mutation_module = "access_request"
    _mutation_class = "ProvisionAccessRequestMutation"

    @classmethod
    def _validate_mutation(cls, user, **data):
        if not user.has_perms(AccessRequestConfig.gql_ict_approve_perms):
            raise PermissionDenied(_("unauthorized"))

    @classmethod
    def _mutate(cls, user, **data):
        _strip_client(data)
        res = AccessRequestService(user).provision(
            data.get('id'), role_ids=data.get('role_ids') or [],
            username=data.get('username'), district_ids=data.get('district_ids'))
        return res if not res['success'] else None

    class Input(OpenIMISMutation.Input):
        id = graphene.UUID(required=True)
        username = graphene.String(required=True)
        role_ids = graphene.List(graphene.Int, required=True)
        district_ids = graphene.List(graphene.Int, required=False)
