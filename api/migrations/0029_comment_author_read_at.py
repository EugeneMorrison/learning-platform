from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('api', '0028_course_reviews')]

    operations = [
        migrations.AddField(
            model_name='comment',
            name='author_read_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
