"""Access Request module configuration and idempotent seed hooks."""
import logging
import uuid

from django.apps import AppConfig
from django.db.models.signals import post_migrate

logger = logging.getLogger(__name__)

MODULE_NAME = 'access_request'

IMIS_ADMINISTRATOR_SYSTEM = 64

# Role ids are site-specific; staff confirm the final roles during approval.
DEFAULT_PROFILES = [
    ('DATA_ENTRY_DISTRICT', 'District Data Entry', 'Capture and edit registry / enrolment data at district level'),
    ('PAYMENT_OFFICER', 'Payment Officer', 'Prepare and manage payment lists and payrolls'),
    ('TARGETING_OFFICER', 'Targeting Officer', 'Manage PMT targeting and household selection'),
    ('GRIEVANCE_OFFICER', 'Grievance Officer', 'Handle complaints and grievance cases'),
    ('READ_ONLY_VIEWER', 'Read-only Viewer', 'View dashboards and reports without edit access'),
]

SECTION_USER_GROUPS = [
    'Executive Office and Corporate Governance',
    'Internal Audit and Assurance',
    'Finance, Disbursement and E Payment',
    'Administration, Human Resources, Registry and Logistics',
    'ICT, Systems and Digital Delivery',
    'Programs, Productive Cash Transfer and Economic Inclusion',
    'Climate Smart Public Works, Targeted Infrastructure, Safeguards and GRM',
    'Monitoring, Evaluation and Data',
]

# PAA (village-level) sections shown only to PAA staff on the public form. Seeded as both
# auth.Group sections (selectable in the dropdown) and matching core.Role rows carrying one
# baseline right — a placeholder to be refined later via the Roles admin.
PAA_SECTION_GROUPS = ['TMO', 'PSSC', 'PSSNA']
PAA_ROLE_BASIC_RIGHTS = [101001]  # insuree/family search — most basic openIMIS right

DEFAULT_CONFIG = {
    'gql_request_search_perms': ['230101'],
    'gql_request_view_perms': ['230102'],
    'gql_manager_approve_perms': ['230201'],
    'gql_ict_approve_perms': ['230202'],
    'gql_profile_manage_perms': ['230301'],
    'public_submit_enabled': True,
    'submit_rate_max': 10,          
    'submit_rate_window': 60,      
    'captcha_enabled': False,      
    'credential_delivery': 'SET_PASSWORD_LINK',  
    'default_user_language': 'en',
    'seed_profiles': True,
    'seed_sections': True,          # seed the RBAC user groups as auth.Group "sections"
}

ALL_RIGHTS = [
    230101, 230102,
    230201, 230202,
    230301,
]


class AccessRequestConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = MODULE_NAME

    gql_request_search_perms = []
    gql_request_view_perms = []
    gql_manager_approve_perms = []
    gql_ict_approve_perms = []
    gql_profile_manage_perms = []
    public_submit_enabled = True
    submit_rate_max = 10
    submit_rate_window = 60
    captcha_enabled = False
    credential_delivery = 'SET_PASSWORD_LINK'
    default_user_language = 'en'
    seed_profiles = True
    seed_sections = True

    def ready(self):
        from core.models import ModuleConfiguration
        cfg = ModuleConfiguration.get_or_default(MODULE_NAME, DEFAULT_CONFIG)
        self.__load_config(cfg)
        post_migrate.connect(on_post_migrate, sender=self)

    @classmethod
    def __load_config(cls, cfg):
        for field in cfg:
            if hasattr(AccessRequestConfig, field):
                setattr(AccessRequestConfig, field, cfg[field])


def on_post_migrate(sender, **kwargs):
    """Idempotent seeding run after this app's tables exist."""
    apps = kwargs.get('apps')
    try:
        _seed_admin_rights(apps)
    except Exception as exc:  # never break the migrate of other apps
        logger.warning("access_request: rights seeding skipped (%s)", exc)
    try:
        if AccessRequestConfig.seed_profiles:
            _seed_profiles(apps)
    except Exception as exc:
        logger.warning("access_request: profile seeding skipped (%s)", exc)
    try:
        if AccessRequestConfig.seed_sections:
            _seed_sections(apps)
            _seed_paa_roles(apps)
    except Exception as exc:
        logger.warning("access_request: section seeding skipped (%s)", exc)


def _seed_admin_rights(apps):
    Role = apps.get_model('core', 'Role')
    RoleRight = apps.get_model('core', 'RoleRight')
    role = Role.objects.filter(is_system=IMIS_ADMINISTRATOR_SYSTEM, validity_to__isnull=True).first()
    if not role:
        return
    for right_id in ALL_RIGHTS:
        if not RoleRight.objects.filter(role=role, right_id=right_id, validity_to__isnull=True).exists():
            RoleRight.objects.create(role=role, right_id=right_id, audit_user_id=1)


def _seed_sections(apps):
    """Idempotently ensure the RBAC user groups exist as django auth.Group rows (the public
    form's Section dropdown loads from these)."""
    Group = apps.get_model('auth', 'Group')
    for name in SECTION_USER_GROUPS + PAA_SECTION_GROUPS:
        Group.objects.get_or_create(name=name)


def _seed_paa_roles(apps):
    """Idempotently ensure the PAA sections (TMO/PSSC/PSSNA) also exist as core.Role rows with a
    baseline right, so they carry some permission out of the box (edited later via the admin)."""
    Role = apps.get_model('core', 'Role')
    RoleRight = apps.get_model('core', 'RoleRight')
    for name in PAA_SECTION_GROUPS:
        role = Role.objects.filter(name=name, validity_to__isnull=True).first()
        if not role:
            role = Role.objects.create(
                name=name, uuid=uuid.uuid4(), is_system=0, is_blocked=False, audit_user_id=1,
            )
        for right_id in PAA_ROLE_BASIC_RIGHTS:
            if not RoleRight.objects.filter(role=role, right_id=right_id, validity_to__isnull=True).exists():
                RoleRight.objects.create(role=role, right_id=right_id, audit_user_id=1)


def _seed_profiles(apps):
    AccessProfile = apps.get_model('access_request', 'AccessProfile')
    User = apps.get_model('core', 'User')
    admin = User.objects.order_by('id').first()
    if not admin:
        return  # no user yet (fresh bootstrap) — profiles can be created later
    for code, name, description in DEFAULT_PROFILES:
        if not AccessProfile.objects.filter(code=code).exists():
            AccessProfile.objects.create(
                id=uuid.uuid4(), code=code, name=name, description=description,
                suggested_role_ids=[], is_active=True, version=1,
                user_created_id=admin.id, user_updated_id=admin.id,
            )
