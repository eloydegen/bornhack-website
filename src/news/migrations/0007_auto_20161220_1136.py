# -*- coding: utf-8 -*-
# Generated by Django 1.10.4 on 2016-12-20 11:36


from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [("news", "0006_remove_newsitem_public")]

    operations = [
        migrations.AlterField(
            model_name="newsitem",
            name="published_at",
            field=models.DateTimeField(blank=True, null=True),
        )
    ]
