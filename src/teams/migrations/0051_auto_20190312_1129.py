# Generated by Django 2.1.5 on 2019-03-12 10:29

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('teams', '0050_team_guide'),
    ]

    operations = [
        migrations.AlterField(
            model_name='team',
            name='guide',
            field=models.TextField(blank=True, default='\n## Preparations\n\n...\n\n## Camp setup\n\n...\n\n## During camp\n\n...\n\n## Takedown\n\n...\n\n## Notes for next year\n\n 1. Remember to take notes\n 1. ...\n', help_text='HowTo guide for this year (and next year)', verbose_name='team guide (Markdown)'),
        ),
    ]