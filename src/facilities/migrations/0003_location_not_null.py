# Generated by Django 3.0.3 on 2020-02-20 08:59

import django.contrib.gis.db.models.fields
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("facilities", "0002_facility_location"),
    ]

    operations = [
        migrations.AlterField(
            model_name="facility",
            name="location",
            field=django.contrib.gis.db.models.fields.PointField(
                help_text="The location of this facility", srid=4326
            ),
        ),
    ]