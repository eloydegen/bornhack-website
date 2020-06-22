# Generated by Django 3.0.3 on 2020-02-09 18:24

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("teams", "0051_auto_20190312_1129"),
    ]

    operations = [
        migrations.CreateModel(
            name="Wish",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("created", models.DateTimeField(auto_now_add=True)),
                ("updated", models.DateTimeField(auto_now=True)),
                (
                    "name",
                    models.CharField(
                        help_text="Short description of the wish", max_length=100
                    ),
                ),
                ("slug", models.SlugField(help_text="The url slug for this wish")),
                (
                    "description",
                    models.TextField(
                        help_text="Description of the needed item. Markdown is supported!"
                    ),
                ),
                (
                    "count",
                    models.IntegerField(default=1, help_text="How many do we need?"),
                ),
                (
                    "fulfilled",
                    models.BooleanField(
                        default=False,
                        help_text="A Wish is marked as fulfilled when we no longer need the thing.",
                    ),
                ),
                (
                    "team",
                    models.ForeignKey(
                        help_text="The team that needs this thing. When in doubt pick Orga :)",
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="wishes",
                        to="teams.Team",
                    ),
                ),
            ],
            options={"abstract": False,},
        ),
    ]
