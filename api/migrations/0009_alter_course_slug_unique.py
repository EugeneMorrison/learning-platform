# Hand-written: now that every row has a value (0008), enforce uniqueness.
# This field definition matches Course.slug exactly so `makemigrations`
# reports "No changes detected" afterwards.
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0008_fill_course_slugs'),
    ]

    operations = [
        migrations.AlterField(
            model_name='course',
            name='slug',
            field=models.SlugField(blank=True, help_text='URL identifier; auto-generated from the title (transliterated) when left blank', max_length=255, unique=True),
        ),
    ]
