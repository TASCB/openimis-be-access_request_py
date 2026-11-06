from django.core.management.base import BaseCommand
from django.db import connection, transaction

from access_request.apps import LEGACY_SECTIONS, SECTION_USER_GROUPS
from access_request.models import AccessProfile, AccessRequest, SectionSponsor
from access_request.title_profiles import TITLE_PROFILES, section_name


class Command(BaseCommand):
    help = 'Merge the former UG sections into the organogram directorates.'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', dest='dry_run')

    def handle(self, *args, **opts):
        from django.contrib.auth.models import Group
        try:
            from approval.models import ApprovalStep
        except ImportError:
            ApprovalStep = None

        dry = opts['dry_run']
        tag = '[dry-run] ' if dry else ''
        touched_profiles = set()

        with transaction.atomic():
            # Surface FK violations in the dry run too.
            with connection.cursor() as cursor:
                cursor.execute('SET CONSTRAINTS ALL IMMEDIATE')

            targets = {}
            for name in SECTION_USER_GROUPS:
                targets[name], created = Group.objects.get_or_create(name=name)
                if created:
                    self.stdout.write(f'{tag}CREATE section {name!r}')

            for old_name, new_name in LEGACY_SECTIONS.items():
                old = Group.objects.filter(name=old_name).first()
                if not old:
                    continue
                new = targets[new_name]
                members = list(old.user_set.all())
                new.user_set.add(*members)
                new.permissions.add(*old.permissions.all())
                profile_ids = list(AccessProfile.objects.filter(section_group=old).values_list('id', flat=True))
                AccessProfile.objects.filter(id__in=profile_ids).update(section_group=new)
                touched_profiles.update(profile_ids)
                requests = AccessRequest.objects.filter(section_group=old).update(section_group=new)
                steps = 0
                if ApprovalStep is not None:
                    steps = ApprovalStep.objects.filter(assigned_group_id=old.id).update(assigned_group_id=new.id)
                sponsor_note = ''
                sponsor = SectionSponsor.objects.filter(section_group=old).first()
                if sponsor:
                    kept = SectionSponsor.objects.filter(section_group=new).first()
                    if kept:
                        sponsor_note = f', sponsor {sponsor.sponsor_role} dropped ({new_name} keeps {kept.sponsor_role})'
                        sponsor.delete()
                    else:
                        sponsor.section_group = new
                        sponsor.save()
                        sponsor_note = f', sponsor {sponsor.sponsor_role} moved'
                self.stdout.write(
                    f'{tag}MERGE {old_name!r} -> {new_name!r}: managers={len(members)} '
                    f'titles={len(profile_ids)} requests={requests} steps={steps}{sponsor_note}')
                old.delete()

            # Titles whose directorate differs from the merged section (CM, CO).
            for code, title, directorate, _roles in TITLE_PROFILES:
                target = targets[section_name(directorate)]
                ids = list(AccessProfile.objects.filter(code=code, is_deleted=False)
                           .exclude(section_group=target).values_list('id', flat=True))
                if ids:
                    AccessProfile.objects.filter(id__in=ids).update(section_group=target)
                    touched_profiles.update(ids)
                    self.stdout.write(f'{tag}TITLE {code} {title} -> {target.name!r}')

            if dry:
                transaction.set_rollback(True)

        if not dry:
            # .update() bypasses the cache refresh.
            for profile in AccessProfile.objects.filter(id__in=touched_profiles):
                profile.update_cache()
        self.stdout.write(self.style.SUCCESS(
            f'Done{" (dry run, nothing saved)" if dry else ""}. Sections: ' + ', '.join(SECTION_USER_GROUPS)))
