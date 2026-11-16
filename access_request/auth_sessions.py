"""Browser sessions: which browsers are signed in as a user, and ending them.

openIMIS signs users in with stateless JWTs and keeps no record of them. This module wraps the
configured JWT decode handler, so every token the backend accepts (GraphQL, REST, refresh) passes
through `check`: the first time a session is seen it is recorded, and a session that was ended is
refused. A session is the user plus the token's `origIat`, which every refresh carries over.

The answer for a session is cached for a minute, so a busy browser costs one database query a minute;
ending a session overwrites its cache entry, so it takes effect on the next request.
"""
import hashlib
import logging
import time
from datetime import datetime, timedelta, timezone as dt_timezone

from django.core.cache import cache
from django.db import IntegrityError
from django.utils import timezone
from graphql_jwt.exceptions import JSONWebTokenError
from graphql_jwt.settings import jwt_settings

logger = logging.getLogger(__name__)

CACHE_SECONDS = 60
ENDED = 'ended'
SESSION_ENDED_MESSAGE = 'Session ended. Sign in again.'


def _cache_key(username, orig_iat):
    return f'access_request:auth_session:{username}:{orig_iat}'


def key_hint(user):
    """A short fingerprint of the key the user's tokens are signed with (never the key itself)."""
    key = getattr(getattr(user, 'i_user', None), 'private_key', None) or ''
    return hashlib.sha256(key.encode()).hexdigest()[:16] if key else ''


def refresh_ends_at(orig_iat):
    """When the session can no longer be renewed, so its tokens stop working for good."""
    signed_in = datetime.fromtimestamp(orig_iat, tz=dt_timezone.utc)
    return signed_in + jwt_settings.JWT_REFRESH_EXPIRATION_DELTA


def _client(request):
    if request is None or not hasattr(request, 'META'):
        return '', ''
    meta = request.META
    forwarded = (meta.get('HTTP_X_FORWARDED_FOR') or '').split(',')[0].strip()
    address = forwarded or meta.get('HTTP_X_REAL_IP') or meta.get('REMOTE_ADDR') or ''
    return (meta.get('HTTP_USER_AGENT') or '')[:1000], address[:45]


def _find_or_record(username, orig_iat, request):
    from core.models import User
    from access_request.models import AuthSession

    session = AuthSession.objects.filter(user__username=username, orig_iat=orig_iat).first()
    if session:
        return session
    user = User.objects.filter(username=username, *User.filter_validity()).first()
    if user is None:
        return None
    agent, address = _client(request)
    try:
        return AuthSession.objects.create(
            user=user, orig_iat=orig_iat, user_agent=agent, ip_address=address,
            key_hint=key_hint(user), last_seen_at=timezone.now(),
        )
    except IntegrityError:
        # another request of the same session recorded it first
        return AuthSession.objects.filter(user=user, orig_iat=orig_iat).first()


def check(payload, request=None):
    """Record the session a valid token belongs to, and refuse it if the session was ended."""
    username = payload.get('username') if isinstance(payload, dict) else None
    orig_iat = payload.get('origIat') if isinstance(payload, dict) else None
    if not username or not isinstance(orig_iat, int):
        return
    key = _cache_key(username, orig_iat)
    known = cache.get(key)
    if known is None:
        session = _find_or_record(username, orig_iat, request)
        if session is None:
            return
        if session.ended_at:
            known = ENDED
        else:
            known = str(session.id)
            now = timezone.now()
            changes = {'last_seen_at': now}
            # a session first seen without its browser (e.g. through a REST call) learns it later
            agent, address = _client(request)
            if agent and not session.user_agent:
                changes.update(user_agent=agent, ip_address=address)
            type(session).objects.filter(pk=session.pk).update(**changes)
        cache.set(key, known, CACHE_SECONDS)
    if known == ENDED:
        raise JSONWebTokenError(SESSION_ENDED_MESSAGE)
    if request is not None:
        request._auth_session_id = known


def install():
    """Wrap the configured JWT decode handler with `check`. Safe to call more than once."""
    inner = jwt_settings.JWT_DECODE_HANDLER
    if getattr(inner, 'tracks_auth_sessions', False):
        return

    def decode(token, context=None):
        payload = inner(token, context)
        try:
            check(payload, context)
        except JSONWebTokenError:
            raise
        except Exception:  # never lock everyone out because the session store failed
            logger.exception('access_request: could not check the browser session')
        return payload

    decode.tracks_auth_sessions = True
    jwt_settings.JWT_DECODE_HANDLER = decode


# --- the signed-in user's own sessions


def _alive(user):
    """The user's sessions whose tokens can still work: not ended, not past renewal, still in use."""
    from access_request.models import AuthSession

    now = timezone.now()
    hint = key_hint(user)
    # Gone for good: past renewal, plus a day for the last token. Kept until then so an ended
    # session stays refused for as long as its tokens could work.
    stale = int((now - jwt_settings.JWT_REFRESH_EXPIRATION_DELTA - timedelta(days=1)).timestamp())
    AuthSession.objects.filter(user=user, orig_iat__lt=stale).delete()
    sessions = AuthSession.objects.filter(
        user=user,
        ended_at__isnull=True,
        orig_iat__gte=int((now - jwt_settings.JWT_REFRESH_EXPIRATION_DELTA).timestamp()),
        # a token lives JWT_EXPIRATION_DELTA after it was issued; unseen for longer, it has expired
        last_seen_at__gte=now - jwt_settings.JWT_EXPIRATION_DELTA,
    )
    # signed with a key the user no longer has (the password changed): dead already
    return [session for session in sessions if not hint or not session.key_hint or session.key_hint == hint]


def own_sessions(user, current_id=None):
    sessions = _alive(user)
    return sorted(
        sessions,
        key=lambda session: (str(session.id) != current_id, -session.last_seen_at.timestamp()),
    )


def end_sessions(user, sessions):
    """End the given sessions of `user`; every token of theirs is refused from the next request on."""
    from access_request.models import AuthSession

    ids = [session.id for session in sessions]
    if not ids:
        return 0
    ended = AuthSession.objects.filter(user=user, id__in=ids, ended_at__isnull=True)
    rows = list(ended)
    ended.update(ended_at=timezone.now())
    for session in rows:
        # refused until its tokens could no longer work anyway: past renewal, plus a day for the last token
        remaining = refresh_ends_at(session.orig_iat).timestamp() + 24 * 3600 - time.time()
        cache.set(_cache_key(user.username, session.orig_iat), ENDED, max(int(remaining), CACHE_SECONDS))
    return len(rows)
