from unittest import mock

from django.contrib.auth.models import Group
from django.core.cache.backends.locmem import LocMemCache
from django.test import TestCase
from rest_framework.test import APIRequestFactory

from core.models import User
from access_request.models import AccessProfile, AccessRequest, AccessUnit, UserCategory
from access_request.services import AccessRequestService, approver_group_id
from access_request.views import AccessRequestSubmitView, SectionListView, UnitListView


class UnitRoutingTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.filter(username='Admin').first()
        cls.edo = Group.objects.create(name='T Executive Office')
        cls.dids = Group.objects.create(name='T IT and Delivery Systems')

        def profile(code):
            p = AccessProfile(code=f'T-{code}', name=code, suggested_role_ids=[], is_active=True)
            p.save(user=cls.admin)
            return p

        def unit(code, section, head=None, reports_to=None):
            return AccessUnit.objects.create(
                code=f'T-{code}', name=f'T {code}', section_group=section,
                group=Group.objects.create(name=f'T unit {code}'), head_profile=head, reports_to=reports_to)

        cls.ed, cls.director, cls.cm, cls.co = (profile(c) for c in ('ED', 'DIDS', 'CM', 'CO'))
        cls.ed_office = unit('ED-OFF', cls.edo, head=cls.ed)
        cls.dids_office = unit('DIDS-OFF', cls.dids, head=cls.director, reports_to=cls.ed_office)
        cls.comm = unit('COMM', cls.dids, head=cls.cm, reports_to=cls.dids_office)

    def test_officer_goes_to_unit_manager(self):
        self.assertEqual(approver_group_id(self.comm, self.co, self.dids.id), self.comm.group_id)

    def test_manager_goes_to_director(self):
        self.assertEqual(approver_group_id(self.comm, self.cm, self.dids.id), self.dids_office.group_id)

    def test_director_goes_to_executive_director(self):
        self.assertEqual(approver_group_id(self.dids_office, self.director, self.dids.id),
                         self.ed_office.group_id)

    def test_top_of_the_chart_and_no_unit_fall_back_to_section(self):
        self.assertEqual(approver_group_id(self.ed_office, self.ed, self.edo.id), self.edo.id)
        self.assertEqual(approver_group_id(None, self.co, self.dids.id), self.dids.id)

    def test_inactive_parent_falls_back_to_section(self):
        AccessUnit.objects.filter(id=self.dids_office.id).update(is_active=False)
        self.comm.refresh_from_db()
        self.assertEqual(approver_group_id(self.comm, self.cm, self.dids.id), self.dids.id)

    def test_provisioned_head_joins_the_unit_they_manage(self):
        user = User.objects.exclude(username='Admin').filter(validity_to__isnull=True).first()
        req = AccessRequest(full_name='C M', email='cm@example.org', profile=self.cm)
        AccessRequestService._join_headed_units(req, user)
        self.assertTrue(user.groups.filter(id=self.comm.group_id).exists())
        req.profile = self.co
        AccessRequestService._join_headed_units(req, user)
        self.assertEqual(user.groups.filter(access_unit__isnull=False).count(), 1)

    def test_public_lists_units_and_keeps_them_out_of_sections(self):
        factory = APIRequestFactory()
        sections = SectionListView.as_view()(factory.get('/sections/')).data['sections']
        self.assertNotIn(self.comm.group_id, [s['id'] for s in sections])
        self.assertIn(self.dids.id, [s['id'] for s in sections])
        units = UnitListView.as_view()(factory.get('/units/')).data['units']
        comm = next(u for u in units if u['code'] == 'T-COMM')
        self.assertEqual(comm['section_group_id'], self.dids.id)


class UnitSubmitValidationTest(UnitRoutingTest):
    def setUp(self):
        cache_patch = mock.patch('access_request.views.cache', LocMemCache(self.id(), {}))
        cache_patch.start()
        self.addCleanup(cache_patch.stop)
        submit_patch = mock.patch(
            'access_request.views.AccessRequestService.submit',
            return_value={'success': True, 'reference_code': 'AR-TEST'})
        self.submit = submit_patch.start()
        self.addCleanup(submit_patch.stop)
        AccessProfile.objects.filter(id=self.co.id).update(unit=self.comm, section_group=self.dids)

    def post(self, **data):
        body = {'request_type': 'NEW', 'full_name': 'Asha Juma', 'email': 'asha@example.org',
                'user_category': UserCategory.TASAF_STAFF, 'section_group_id': self.dids.id, **data}
        request = APIRequestFactory().post('/submit/', body, format='json')
        return AccessRequestSubmitView.as_view()(request)

    def test_unit_required_when_the_section_has_units(self):
        res = self.post(profile_id=str(self.co.id))
        self.assertEqual(res.status_code, 400)
        self.assertIn('unit', res.data['fields'])

    def test_unit_of_another_section_rejected(self):
        res = self.post(unit_id=str(self.ed_office.id), profile_id=str(self.co.id))
        self.assertEqual(res.data['fields'].get('unit_id'), 'invalid')

    def test_title_of_another_unit_rejected(self):
        res = self.post(unit_id=str(self.dids_office.id), profile_id=str(self.co.id))
        self.assertEqual(res.data['fields'].get('profile_id'), 'invalid')

    def test_valid_unit_and_title_pass_the_unit_on(self):
        res = self.post(unit_id=str(self.comm.id), profile_id=str(self.co.id))
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(self.submit.call_args[0][0]['unit_id'], str(self.comm.id))
