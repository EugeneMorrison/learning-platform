from django.db import migrations


def move_permission(apps, schema_editor, source, destination):
    ContentType = apps.get_model('contenttypes', 'ContentType')
    Permission = apps.get_model('auth', 'Permission')
    alias = schema_editor.connection.alias
    target, _ = ContentType.objects.using(alias).get_or_create(app_label='api', model=destination)
    # Preserve the permission row's ID and therefore user/group grants.
    Permission.objects.using(alias).filter(
        content_type__app_label='api', content_type__model=source,
        codename='export_any_course').update(content_type=target)


def forward(apps, schema_editor):
    move_permission(apps, schema_editor, 'courseexportjob', 'course')


def backward(apps, schema_editor):
    move_permission(apps, schema_editor, 'course', 'courseexportjob')


class Migration(migrations.Migration):
    dependencies = [('api', '0025_course_export_job')]
    operations = [
        migrations.RunPython(forward, backward),
        migrations.AlterModelOptions(name='course', options={
            'ordering': ['sort_order', '-created_at'],
            'permissions': [('export_any_course', 'Can export any course and its author materials')],
        }),
        migrations.DeleteModel(name='CourseExportJob'),
    ]
