from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from access_request.apps import DEFAULT_PROFILES
from access_request.models import AccessProfile, AccessUnit
from access_request.title_profiles import TITLE_PROFILES, UNIT_HEAD_ROLE, UNITS, section_name


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
        heads = {head for _c, _n, _d, head, _r, _t in UNITS}
        unit_of = {title: unit for unit, *_rest, titles in UNITS for title in titles}
        with transaction.atomic():
            units = self._seed_units(group_ids, tag, dry, counts)
            for code, title, group, roles in TITLE_PROFILES:
                if code in heads and UNIT_HEAD_ROLE not in roles:
                    roles = roles + [UNIT_HEAD_ROLE]
                ids = [role_ids[r] for r in roles if r in role_ids]
                missing_roles.update(r for r in roles if r not in role_ids)
                description = f'{group}: {", ".join(roles)}'
                section_id = group_ids.get(section_name(group))
                unit = units.get(unit_of.get(code))
                unit_id = unit.id if unit else None
                profile = AccessProfile.objects.filter(code=code, is_deleted=False).first()
                if not profile:
                    counts['created'] += 1
                    self.stdout.write(f'{tag}CREATE {code} {title} -> {roles}')
                    if not dry:
                        AccessProfile(code=code, name=title, description=description,
                                      suggested_role_ids=ids, section_group_id=section_id,
                                      unit_id=unit_id, is_active=True).save(user=user)
                elif opts['update'] and (profile.suggested_role_ids != ids or profile.name != title
                                         or profile.section_group_id != section_id
                                         or profile.unit_id != unit_id):
                    counts['updated'] += 1
                    self.stdout.write(f'{tag}UPDATE {code} {title} -> {roles}')
                    if not dry:
                        profile.update(user=user, data={'name': title, 'description': description,
                                                        'suggested_role_ids': ids,
                                                        'section_group_id': section_id,
                                                        'unit_id': unit_id})
                elif unit_id and not profile.unit_id:
                    counts['updated'] += 1
                    self.stdout.write(f'{tag}UNIT {code} -> {unit.code}')
                    if not dry:
                        profile.update(user=user, data={'unit_id': unit_id})
                else:
                    counts['kept'] += 1
            if not dry:
                self._link_heads(units)

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

    def _seed_units(self, group_ids, tag, dry, counts):
        from django.contrib.auth.models import Group
        counts.setdefault('units', 0)
        units = {u.code: u for u in AccessUnit.objects.all()}
        for order, (code, name, directorate, _head, _reports, _titles) in enumerate(UNITS):
            section_id = group_ids.get(section_name(directorate))
            unit = units.get(code)
            if unit and unit.name == name and unit.section_group_id == section_id:
                continue
            counts['units'] += 1
            self.stdout.write(f'{tag}UNIT {"UPDATE" if unit else "CREATE"} {code} {name}')
            if dry or not section_id:
                continue
            if unit:
                unit.name, unit.section_group_id, unit.sort_order = name, section_id, order
                unit.group.name = name
                unit.group.save()
                unit.save()
            else:
                group, _ = Group.objects.get_or_create(name=name)
                units[code] = AccessUnit.objects.create(
                    code=code, name=name, section_group_id=section_id, group=group, sort_order=order)
        return units

    @staticmethod
    def _link_heads(units):
        profiles = {p.code: p.id for p in AccessProfile.objects.filter(is_deleted=False)}
        for code, _name, _dir, head, reports_to, _titles in UNITS:
            unit = units.get(code)
            if not unit:
                continue
            reports = units.get(reports_to)
            AccessUnit.objects.filter(id=unit.id).update(
                head_profile_id=profiles.get(head), reports_to_id=reports.id if reports else None)
