"""GraphQL object types for the Access Request module."""
import graphene
from django.contrib.contenttypes.models import ContentType
from graphene_django import DjangoObjectType

from approval.gql_queries import ApprovalRequestGQLType
from approval.models import ApprovalRequest

from core import ExtendedConnection
from core.models import InteractiveUser
from access_request.models import AccessProfile, AccessRequest


class AccessProfileGQLType(DjangoObjectType):
    uuid = graphene.String(source='uuid')

    class Meta:
        model = AccessProfile
        interfaces = (graphene.relay.Node,)
        filter_fields = {
            "id": ["exact"],
            "code": ["exact", "istartswith", "icontains", "iexact"],
            "name": ["exact", "istartswith", "icontains", "iexact"],
            "is_active": ["exact"],
            "is_deleted": ["exact"],
            "version": ["exact"],
        }
        connection_class = ExtendedConnection


class AccessRequestGQLType(DjangoObjectType):
    uuid = graphene.String(source='uuid')
    # Active accounts already using this email, looked up live so reviewers see the
    # current state. Not exposed publicly: it would tell anyone whether an email has an account.
    existing_user_logins = graphene.List(graphene.String)
    # The engine request behind this application. Resolved here, under the access request's own
    # rights, so a line manager can see the chain without holding the engine's search right.
    approval = graphene.Field(ApprovalRequestGQLType)

    def resolve_approval(self, info):
        return ApprovalRequest.objects.filter(
            content_type=ContentType.objects.get_for_model(AccessRequest),
            object_id=str(self.id), is_deleted=False,
        ).order_by('-date_created').first()

    def resolve_existing_user_logins(self, info):
        if not self.email:
            return []
        return list(InteractiveUser.objects.filter(
            email__iexact=self.email.strip(), validity_to__isnull=True,
        ).order_by('login_name').values_list('login_name', flat=True))

    class Meta:
        model = AccessRequest
        interfaces = (graphene.relay.Node,)
        filter_fields = {
            "id": ["exact"],
            "reference_code": ["exact", "istartswith", "icontains", "iexact"],
            "request_type": ["exact", "in"],
            "full_name": ["exact", "istartswith", "icontains", "iexact"],
            "organization_paa": ["exact", "icontains"],
            "section": ["exact", "icontains"],
            "section_group_id": ["exact"],
            "designation": ["exact", "icontains"],
            "email": ["exact", "icontains"],
            "user_category": ["exact", "in"],
            "administrative_level": ["exact", "in"],
            "status": ["exact", "in"],
            "profile_id": ["exact"],
            "requested_location_id": ["exact"],
            "is_deleted": ["exact"],
            "date_created": ["exact", "lt", "lte", "gt", "gte"],
            "version": ["exact"],
        }
        connection_class = ExtendedConnection


class SectionManagerGQLType(graphene.ObjectType):
    user_id = graphene.String()
    username = graphene.String()
    other_names = graphene.String()
    last_name = graphene.String()
    can_approve = graphene.Boolean()


class AccessSectionGQLType(graphene.ObjectType):
    section_id = graphene.Int()
    section_name = graphene.String()
    managers = graphene.List(SectionManagerGQLType)
