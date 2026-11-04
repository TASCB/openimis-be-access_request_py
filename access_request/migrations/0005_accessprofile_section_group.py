from django.db import migrations, models
import django.db.models.deletion


def fill_title_sections(apps, schema_editor):
    from access_request.title_profiles import TITLE_PROFILES, section_name
    AccessProfile = apps.get_model('access_request', 'AccessProfile')
    Group = apps.get_model('auth', 'Group')
    groups = dict(Group.objects.values_list('name', 'id'))
    for code, _title, group, _roles in TITLE_PROFILES:
        group_id = groups.get(section_name(group))
        if group_id:
            AccessProfile.objects.filter(code=code, section_group__isnull=True).update(section_group_id=group_id)


class Migration(migrations.Migration):

    dependencies = [
        ('auth', '0012_alter_user_first_name_max_length'),
        ('access_request', '0004_sectionsponsor'),
    ]

    operations = [
        migrations.AddField(
            model_name='accessprofile',
            name='section_group',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                                    related_name='access_profiles', to='auth.group'),
        ),
        migrations.AddField(
            model_name='historicalaccessprofile',
            name='section_group',
            field=models.ForeignKey(blank=True, db_constraint=False, null=True,
                                    on_delete=django.db.models.deletion.DO_NOTHING,
                                    related_name='+', to='auth.group'),
        ),
        migrations.RunPython(fill_title_sections, migrations.RunPython.noop),
    ]
