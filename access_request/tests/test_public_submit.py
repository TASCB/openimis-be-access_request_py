from unittest import mock

from django.core.cache.backends.locmem import LocMemCache
from django.test import SimpleTestCase, TestCase
from rest_framework.test import APIRequestFactory

from core.models import InteractiveUser, User
from access_request.gql_queries import AccessRequestGQLType
from access_request.models import AccessRequest, RequestStatus, UserCategory
from access_request.views import AccessRequestSubmitView, client_ip, normalize_phone


class NormalizePhoneTest(SimpleTestCase):
    def test_accepted_forms(self):
        for raw in ('+255 712 345 678', '255712345678', '0712345678', '0712-345-678',
                    '(0712) 345 678', '712345678', '0654321098', '+255222123456'):
            self.assertIsNotNone(normalize_phone(raw), raw)
        self.assertEqual(normalize_phone('0712 345 678'), '+255712345678')
        self.assertEqual(normalize_phone('+255 712 345 678'), '+255712345678')

    def test_rejected_forms(self):
        for raw in ('12345', 'abc', '+1 202 555 0147', '0812345678', '07123456789',
                    '071234567', '+255 812 345 678', '0712abc678'):
            self.assertIsNone(normalize_phone(raw), raw)


class PublicSubmitTest(TestCase):
    VALID = {
        'request_type': 'NEW', 'full_name': 'Asha Juma', 'email': 'asha.juma@example.org',
        'phone': '', 'section': 'ICT', 'user_category': UserCategory.TASAF_STAFF,
    }

    def setUp(self):
        self.factory = APIRequestFactory()
        cache_patch = mock.patch('access_request.views.cache', LocMemCache(self.id(), {}))
        cache_patch.start()
        self.addCleanup(cache_patch.stop)
        submit_patch = mock.patch(
            'access_request.views.AccessRequestService.submit',
            return_value={'success': True, 'reference_code': 'AR-TEST'})
        self.submit = submit_patch.start()
        self.addCleanup(submit_patch.stop)

    def post(self, **overrides):
        request = self.factory.post('/api/access_request/submit/', {**self.VALID, **overrides}, format='json')
        return AccessRequestSubmitView.as_view()(request)

    def test_valid_submission_without_phone(self):
        res = self.post()
        self.assertEqual(res.status_code, 200, res.data)
        self.assertIsNone(self.submit.call_args[0][0]['phone'])

    def test_phone_is_normalised(self):
        res = self.post(phone='0712 345 678')
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(self.submit.call_args[0][0]['phone'], '+255712345678')

    def test_invalid_phone_rejected(self):
        res = self.post(phone='12345')
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.data, {'error': 'invalid_fields', 'fields': {'phone': 'invalid'}})
        self.submit.assert_not_called()

    def test_invalid_email_rejected(self):
        for bad in ('not-an-email', 'a@b', 'asha@@example.org', 'asha juma@example.org'):
            res = self.post(email=bad)
            self.assertEqual(res.status_code, 400, bad)
            self.assertEqual(res.data['fields'], {'email': 'invalid'}, bad)
        self.submit.assert_not_called()

    def test_too_long_fields_rejected(self):
        res = self.post(full_name='x' * 256, phone='0' * 51)
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.data['fields'], {'full_name': 'too_long', 'phone': 'too_long'})

    def test_non_string_phone_does_not_crash(self):
        res = self.post(phone=712345678)
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(self.submit.call_args[0][0]['phone'], '+255712345678')

    def test_missing_fields_still_reported_first(self):
        res = self.post(email='', phone='bad')
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.data['error'], 'missing_fields')
        self.assertIn('email', res.data['fields'])

    def _existing_request(self, status):
        user = User.objects.filter(i_user__isnull=False).first()
        AccessRequest(full_name='Asha Juma', email='Asha.Juma@Example.org', status=status).save(user=user)

    def test_open_request_blocks_duplicate_case_insensitively(self):
        for status in (RequestStatus.SUBMITTED, RequestStatus.MANAGER_APPROVED,
                       RequestStatus.ICT_APPROVED, RequestStatus.FAILED):
            AccessRequest.objects.filter(email__iexact=self.VALID['email']).delete()
            self._existing_request(status)
            res = self.post()
            self.assertEqual(res.status_code, 409, status)
            self.assertEqual(res.data, {'error': 'duplicate_request', 'fields': {'email': 'duplicate'}})
        self.submit.assert_not_called()

    def test_closed_request_allows_new_application(self):
        for status in (RequestStatus.REJECTED, RequestStatus.PROVISIONED):
            AccessRequest.objects.filter(email__iexact=self.VALID['email']).delete()
            self._existing_request(status)
            res = self.post()
            self.assertEqual(res.status_code, 200, status)

    def test_rate_limit_is_per_applicant_behind_nginx(self):
        # Every proxied request reaches Django from the nginx address; X-Real-IP carries the applicant.
        def post_from(ip):
            request = self.factory.post('/api/access_request/submit/', {**self.VALID, 'hp': 'bot'},
                                        format='json', REMOTE_ADDR='172.23.0.6', HTTP_X_REAL_IP=ip)
            return AccessRequestSubmitView.as_view()(request)
        with mock.patch('access_request.views.AccessRequestConfig.submit_rate_max', 3):
            codes = [post_from('41.59.1.1').status_code for _ in range(4)]
            self.assertEqual(codes, [200, 200, 200, 429])
            self.assertEqual(post_from('41.59.2.2').status_code, 200)


class ClientIpTest(SimpleTestCase):
    def test_prefers_x_real_ip(self):
        request = APIRequestFactory().get('/', REMOTE_ADDR='172.23.0.6', HTTP_X_REAL_IP='41.59.1.1')
        self.assertEqual(client_ip(request), '41.59.1.1')

    def test_falls_back_to_remote_addr(self):
        request = APIRequestFactory().get('/', REMOTE_ADDR='127.0.0.1')
        self.assertEqual(client_ip(request), '127.0.0.1')


class ExistingUserLoginsTest(TestCase):
    def test_matches_active_users_case_insensitively(self):
        user = InteractiveUser.objects.filter(validity_to__isnull=True).exclude(email__isnull=True) \
            .exclude(email='').first()
        if not user:
            self.skipTest('no interactive user with an email in the test database')
        expected = sorted(InteractiveUser.objects.filter(
            email__iexact=user.email, validity_to__isnull=True).values_list('login_name', flat=True))
        req = AccessRequest(email=f'  {user.email.upper()} ')
        self.assertEqual(AccessRequestGQLType.resolve_existing_user_logins(req, None), expected)

    def test_no_match(self):
        req = AccessRequest(email='nobody-here-7f3a@example.invalid')
        self.assertEqual(AccessRequestGQLType.resolve_existing_user_logins(req, None), [])
