from unittest import mock

from django.core.cache.backends.locmem import LocMemCache
from django.test import RequestFactory, TestCase
from graphql_jwt.exceptions import JSONWebTokenError

from core.models import User
from access_request import auth_sessions
from access_request.models import AuthSession


def payload(user, orig_iat):
    return {'username': user.username, 'origIat': orig_iat, 'exp': orig_iat + 86400}


class AuthSessionTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.filter(username='Admin').first()

    def setUp(self):
        # a private cache per test, so no answer leaks from one test into another
        # (caches of the same name share their store, hence the test's own name)
        cache = LocMemCache(self.id(), {})
        cache.clear()
        patcher = mock.patch.object(auth_sessions, 'cache', cache)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.now = int(auth_sessions.timezone.now().timestamp())

    def request(self, agent='Mozilla/5.0 (X11; Linux x86_64) Firefox/131.0'):
        return RequestFactory().get('/', HTTP_USER_AGENT=agent, REMOTE_ADDR='10.0.0.9')

    def test_records_a_session_once_with_its_browser(self):
        request = self.request()
        auth_sessions.check(payload(self.user, self.now), request)
        auth_sessions.check(payload(self.user, self.now), self.request())
        session = AuthSession.objects.get(user=self.user, orig_iat=self.now)
        self.assertEqual(session.ip_address, '10.0.0.9')
        self.assertIn('Firefox', session.user_agent)
        self.assertEqual(request._auth_session_id, str(session.id))

    def test_an_ended_session_is_refused(self):
        auth_sessions.check(payload(self.user, self.now), self.request())
        session = AuthSession.objects.get(user=self.user, orig_iat=self.now)
        self.assertEqual(auth_sessions.end_sessions(self.user, [session]), 1)
        with self.assertRaisesMessage(JSONWebTokenError, auth_sessions.SESSION_ENDED_MESSAGE):
            auth_sessions.check(payload(self.user, self.now), self.request())

    def test_ending_takes_effect_despite_the_cached_answer(self):
        auth_sessions.check(payload(self.user, self.now), self.request())  # cached as active
        session = AuthSession.objects.get(user=self.user, orig_iat=self.now)
        auth_sessions.end_sessions(self.user, [session])
        with self.assertRaises(JSONWebTokenError):
            auth_sessions.check(payload(self.user, self.now), self.request())

    def test_other_sessions_keep_working(self):
        auth_sessions.check(payload(self.user, self.now), self.request())
        auth_sessions.check(payload(self.user, self.now - 60), self.request())
        auth_sessions.end_sessions(self.user, AuthSession.objects.filter(orig_iat=self.now - 60))
        auth_sessions.check(payload(self.user, self.now), self.request())  # no error

    def test_own_sessions_put_this_one_first_and_leave_out_ended_ones(self):
        for orig_iat in (self.now - 120, self.now - 60, self.now):
            auth_sessions.check(payload(self.user, orig_iat), self.request())
        sessions = {s.orig_iat: s for s in AuthSession.objects.filter(user=self.user)}
        auth_sessions.end_sessions(self.user, [sessions[self.now - 120]])
        current = str(sessions[self.now - 60].id)
        listed = auth_sessions.own_sessions(self.user, current)
        self.assertEqual([s.orig_iat for s in listed][:1], [self.now - 60])
        self.assertNotIn(self.now - 120, [s.orig_iat for s in listed])

    def test_sessions_signed_with_an_old_key_are_not_listed(self):
        auth_sessions.check(payload(self.user, self.now), self.request())
        AuthSession.objects.filter(user=self.user, orig_iat=self.now).update(key_hint='0000000000000000')
        self.assertEqual(
            [s for s in auth_sessions.own_sessions(self.user) if s.orig_iat == self.now], [])

    def test_tokens_without_a_sign_in_time_are_left_alone(self):
        auth_sessions.check({'username': self.user.username}, self.request())
        self.assertFalse(AuthSession.objects.filter(user=self.user).exists())

    def test_install_wraps_the_decode_handler_once(self):
        from graphql_jwt.settings import jwt_settings
        auth_sessions.install()
        handler = jwt_settings.JWT_DECODE_HANDLER
        auth_sessions.install()
        self.assertIs(jwt_settings.JWT_DECODE_HANDLER, handler)
        self.assertTrue(handler.tracks_auth_sessions)
