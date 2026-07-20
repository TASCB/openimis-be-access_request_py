"""GraphQL object types for the Access Request module."""
import graphene
from graphene_django import DjangoObjectType

from core import ExtendedConnection
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
