"""GraphQL schema (Query + Mutation) for the Access Request module.

Concatenated into the global openIMIS schema by the assembly (same mechanism as
``training`` / ``payment_cycle``).
"""
import graphene
import graphene_django_optimizer as gql_optimizer
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.utils.translation import gettext as _

from core.schema import OrderedDjangoFilterConnectionField
from core.services import wait_for_mutation

from access_request.apps import AccessRequestConfig
from access_request.models import AccessProfile, AccessRequest
from access_request.gql_queries import (
    AccessProfileGQLType, AccessRequestGQLType,
)
from access_request.gql_mutations import (
    CreateAccessProfileMutation, UpdateAccessProfileMutation, DeleteAccessProfileMutation,
    ProvisionAccessRequestMutation,
)


def _check(user, perms):
    if type(user) is AnonymousUser or not user.id or not user.has_perms(perms):
        raise PermissionDenied(_("unauthorized"))


class Query(graphene.ObjectType):
    access_request = OrderedDjangoFilterConnectionField(
        AccessRequestGQLType,
        orderBy=graphene.List(of_type=graphene.String),
        client_mutation_id=graphene.String(),
        show_deleted=graphene.Boolean(),
    )
    access_profile = OrderedDjangoFilterConnectionField(
        AccessProfileGQLType,
        orderBy=graphene.List(of_type=graphene.String),
        client_mutation_id=graphene.String(),
        show_deleted=graphene.Boolean(),
    )

    def resolve_access_request(self, info, **kwargs):
        _check(info.context.user, AccessRequestConfig.gql_request_search_perms)
        filters = [] if kwargs.get('show_deleted') else [Q(is_deleted=False)]
        client_mutation_id = kwargs.get('client_mutation_id')
        if client_mutation_id:
            wait_for_mutation(client_mutation_id)
            filters.append(Q(mutations__mutation__client_mutation_id=client_mutation_id))
        return gql_optimizer.query(AccessRequest.objects.filter(*filters).distinct(), info)

    def resolve_access_profile(self, info, **kwargs):
        user = info.context.user
        if type(user) is AnonymousUser or not user.id or not (
            user.has_perms(AccessRequestConfig.gql_request_search_perms)
            or user.has_perms(AccessRequestConfig.gql_profile_manage_perms)
        ):
            raise PermissionDenied(_("unauthorized"))
        filters = [] if kwargs.get('show_deleted') else [Q(is_deleted=False)]
        client_mutation_id = kwargs.get('client_mutation_id')
        if client_mutation_id:
            wait_for_mutation(client_mutation_id)
            filters.append(Q(mutations__mutation__client_mutation_id=client_mutation_id))
        return gql_optimizer.query(AccessProfile.objects.filter(*filters).distinct(), info)


class Mutation(graphene.ObjectType):
    create_access_profile = CreateAccessProfileMutation.Field()
    update_access_profile = UpdateAccessProfileMutation.Field()
    delete_access_profile = DeleteAccessProfileMutation.Field()

    provision_access_request = ProvisionAccessRequestMutation.Field()
