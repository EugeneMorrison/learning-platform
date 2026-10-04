# Hand-written: adds sales/landing-page fields to Course.
# `slug` is added NON-unique and blank here so it can coexist with existing
# rows (all get ''); it is filled in 0008 and flipped to unique in 0009.
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0006_alter_block_type'),
    ]

    operations = [
        migrations.AddField(
            model_name='course',
            name='slug',
            field=models.SlugField(blank=True, default='', max_length=255),
        ),
        migrations.AddField(
            model_name='course',
            name='tagline',
            field=models.CharField(blank=True, help_text='Short marketing subtitle shown on the course card', max_length=200),
        ),
        migrations.AddField(
            model_name='course',
            name='cover',
            field=models.ImageField(blank=True, help_text='Cover image for the course card (stored under MEDIA_ROOT/covers/)', upload_to='covers/'),
        ),
        migrations.AddField(
            model_name='course',
            name='price',
            field=models.DecimalField(decimal_places=2, default=0, help_text='Price in rubles (0 = free)', max_digits=10),
        ),
        migrations.AddField(
            model_name='course',
            name='old_price',
            field=models.DecimalField(blank=True, decimal_places=2, help_text='Original price for a strikethrough discount; leave empty if none', max_digits=10, null=True),
        ),
        migrations.AddField(
            model_name='course',
            name='sort_order',
            field=models.PositiveIntegerField(default=0, help_text='Manual ordering on the landing page (lower = earlier)'),
        ),
        migrations.AddField(
            model_name='course',
            name='stepik_id',
            field=models.PositiveIntegerField(blank=True, help_text='Linked Stepik course id, if the course also lives on Stepik', null=True, unique=True),
        ),
        migrations.AlterModelOptions(
            name='course',
            options={'ordering': ['sort_order', '-created_at']},
        ),
    ]
