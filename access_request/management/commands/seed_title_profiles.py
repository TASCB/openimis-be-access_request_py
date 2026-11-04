from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from access_request.apps import DEFAULT_PROFILES
from access_request.models import AccessProfile
from access_request.title_profiles import TITLE_PROFILES, section_name


class Command(BaseCommand):
    help = 'Create one access profile per TASAF job title, with its suggested roles.'

    def add_arguments(self, parser):
        parser.add_argument('--update', action='store_true',
                            help='Also reset name and suggested roles of existing title profiles.')
        parser.add_argument('--user', default='Admin', help='Login recorded as the editor.')
        parser.add_argument('--dry-run', action='store_true', dest='dry_run')

    def handle(self, *args, **opts):
        from django.contrib.auth.models import Group
        from core.models import Role, User

        user = User.objects.filter(username=opts['user']).first()
        if not user:
            raise CommandError(f"Unknown user {opts['user']!r}")
        role_ids = dict(Role.objects.filter(validity_to__isnull=True).values_list('name', 'id'))
        group_ids = dict(Group.objects.values_list('name', 'id'))
        tag = '[dry-run] ' if opts['dry_run'] else ''  # dry run writes nothing: saves also update the cache
        counts = {'created': 0, 'updated': 0, 'kept': 0, 'retired': 0}
        missing_roles = set()

        dry = opts['dry_run']
        with transaction.atomic():
            for code, title, group, roles in TITLE_PROFILES:
                ids = [role_ids[r] for r in roles if r in role_ids]
                missing_roles.update(r for r in roles if r not in role_ids)
                description = f'{group}: {", ".join(roles)}'
                section_id = group_ids.get(section_name(group))
                profile = AccessProfile.objects.filter(code=code, is_deleted=False).first()
                if not profile:
                    counts['created'] += 1
                    self.stdout.write(f'{tag}CREATE {code} {title} -> {roles}')
                    if not dry:
                        AccessProfile(code=code, name=title, description=description,
                                      suggested_role_ids=ids, section_group_id=section_id,
                                      is_active=True).save(user=user)
                elif opts['update'] and (profile.suggested_role_ids != ids or profile.name != title
                                         or profile.section_group_id != section_id):
                    counts['updated'] += 1
                    self.stdout.write(f'{tag}UPDATE {code} {title} -> {roles}')
                    if not dry:
                        profile.update(user=user, data={'name': title, 'description': description,
                                                        'suggested_role_ids': ids,
                                                        'section_group_id': section_id})
                else:
                    counts['kept'] += 1

            for code, _name, _desc in DEFAULT_PROFILES:
                for profile in AccessProfile.objects.filter(code=code, is_active=True, is_deleted=False):
                    counts['retired'] += 1
                    self.stdout.write(f'{tag}RETIRE {code} (placeholder, no roles)')
                    if not dry:
                        # .update(): pre_save resets a False boolean back to its default True.
                        AccessProfile.objects.filter(id=profile.id).update(is_active=False)
                        AccessProfile.objects.get(id=profile.id).update_cache()

        if missing_roles:
            self.stdout.write(self.style.WARNING(
                'Roles not on this server, left out of the profiles: ' + ', '.join(sorted(missing_roles))
                + '. Run seed_tasaf_roles, then this command with --update.'))
        self.stdout.write(self.style.SUCCESS(
            'Done. ' + ' '.join(f'{k}={v}' for k, v in counts.items())))
