# Generated by Django 3.2.16 on 2022-12-04 12:53

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('shop', '0081_alter_refund_created_by'),
    ]

    operations = [
        migrations.AlterField(
            model_name='quickpayapirequest',
            name='body',
            field=models.JSONField(default=dict),
        ),
    ]
