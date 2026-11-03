from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('api', '0022_matching_block')]

    operations = [
        migrations.AlterField(
            model_name='block', name='type',
            field=models.CharField(
                choices=[('TEXT', 'Text Block'), ('QUIZ', 'Quiz Block'),
                         ('CODE', 'Code Block'), ('FILL', 'Fill-in-the-blanks Block'),
                         ('SORT', 'Sorting Block'), ('MATCH', 'Matching Block'), ('TABLE', 'Table Block')],
                help_text='Block type (TEXT/QUIZ/CODE/FILL/SORT/MATCH/TABLE)', max_length=10,
            ),
        ),
    ]
