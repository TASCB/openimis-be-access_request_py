"""GraphQL for the signed-in user's own browser sessions (see `auth_sessions`)."""
from datetime import datetime, timezone as dt_timezone

import graphene
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied
from django.utils import timezone
from django.utils.translation import gettext as _
from graphql_jwt.utils import get_credentials, get_payload

from access_request import auth_sessions


def _signed_in(info):
    user = info.context.user
    if type(user) is AnonymousUser or not user.id:
        raise PermissionDenied(_("unauthorized"))
    return user


def _current_id(info):
    """The id of the session this request comes from (recorded when its token was checked)."""
    request = info.context
    if getattr(request, '_auth_session_id', None) is None:
        token = get_credentials(request)
        if token:
            get_payload(token, request)  # checks the session, which notes its id on the request
    return getattr(request, '_auth_session_id', None)


class AuthSessionGQLType(graphene.ObjectType):
    id = graphene.UUID(required=True)
    user_agent = graphene.String(required=True)
    ip_address = graphene.String(required=True)
    signed_in_at = graphene.DateTime(required=True)
    last_seen_at = graphene.DateTime(required=True)
    # After this the session cannot be renewed and its browser signs in again.
    expires_at = graphene.DateTime(required=True)
    is_current = graphene.Boolean(required=True)


def _aware(value):
    """Stored times are naive in the server's zone when USE_TZ is off; say which zone that is."""
    return timezone.make_aware(value, timezone.get_default_timezone()) if timezone.is_naive(value) else value


def _gql(session, current_id):
    return AuthSessionGQLType(
        id=session.id,
        user_agent=session.user_agent,
        ip_address=session.ip_address,
        signed_in_at=datetime.fromtimestamp(session.orig_iat, tz=dt_timezone.utc),
        last_seen_at=_aware(session.last_seen_at),
        expires_at=auth_sessions.refresh_ends_at(session.orig_iat),
        is_current=str(session.id) == current_id,
    )


class AuthSessionQuery(graphene.ObjectType):
    my_auth_sessions = graphene.List(graphene.NonNull(AuthSessionGQLType), required=True)

    def resolve_my_auth_sessions(self, info):
        user = _signed_in(info)
        current = _current_id(info)
        return [_gql(session, current) for session in auth_sessions.own_sessions(user, current)]


class EndAuthSessionMutation(graphene.Mutation):
    """Sign one of the user's other browsers out."""

    class Arguments:
        id = graphene.UUID(required=True)

    ended = graphene.Int(required=True)

    def mutate(self, info, id):
        user = _signed_in(info)
        if str(id) == _current_id(info):
            raise PermissionDenied(_("Use sign out to end this session"))
        sessions = [session for session in auth_sessions.own_sessions(user) if session.id == id]
        return EndAuthSessionMutation(ended=auth_sessions.end_sessions(user, sessions))


class EndOtherAuthSessionsMutation(graphene.Mutation):
    """Sign every browser out except this one."""

    ended = graphene.Int(required=True)

    def mutate(self, info):
        user = _signed_in(info)
        current = _current_id(info)
        sessions = [session for session in auth_sessions.own_sessions(user) if str(session.id) != current]
        return EndOtherAuthSessionsMutation(ended=auth_sessions.end_sessions(user, sessions))


class EndCurrentAuthSessionMutation(graphene.Mutation):
    """End this browser's session, so its token is refused even if a copy of it survives sign-out."""

    ended = graphene.Int(required=True)

    def mutate(self, info):
        user = _signed_in(info)
        current = _current_id(info)
        sessions = [session for session in auth_sessions.own_sessions(user) if str(session.id) == current]
        return EndCurrentAuthSessionMutation(ended=auth_sessions.end_sessions(user, sessions))


class AuthSessionMutation(graphene.ObjectType):
    end_auth_session = EndAuthSessionMutation.Field()
    end_other_auth_sessions = EndOtherAuthSessionsMutation.Field()
    end_current_auth_session = EndCurrentAuthSessionMutation.Field()
