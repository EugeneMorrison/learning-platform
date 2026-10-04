# Hand-written data migration: give every existing course a unique slug.
#
# We import slugify DIRECTLY and build the slug here instead of calling
# Course.save(). Migrations run against a frozen historical model that has
# none of the model's custom methods (save/_generate_unique_slug), so relying
# on save() would silently do nothing.
from django.db import migrations
from slugify import slugify

SLUG_MAX_LENGTH = 255
SUFFIX_RESERVE = 5  # leave room for a "-NN" dedupe suffix within the field limit


def fill_slugs(apps, schema_editor):
    Course = apps.get_model('api', 'Course')
    # Pre-seed with every slug already present so we can never mint a
    # duplicate, even if this migration were somehow applied twice.
    used = set(Course.objects.exclude(slug='').values_list('slug', flat=True))
    # No .iterator(): on SQLite, writing to the table you're iterating over can
    # skip or repeat rows. The dataset is tiny, so just load it in one batch.
    # order_by keeps the -N suffixes deterministic across runs.
    for course in Course.objects.order_by('created_at'):
        if course.slug:
            continue
        # Fallback to 'course' when the title transliterates to nothing
        # (e.g. a title made only of punctuation/emoji).
        base = slugify(course.title or '')[:SLUG_MAX_LENGTH - SUFFIX_RESERVE].rstrip('-') or 'course'
        slug = base
        n = 2
        while slug in used:
            slug = f"{base}-{n}"
            n += 1
        course.slug = slug
        course.save(update_fields=['slug'])
        used.add(slug)


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0007_course_sales_fields'),
    ]

    operations = [
        migrations.RunPython(fill_slugs, migrations.RunPython.noop),
    ]
