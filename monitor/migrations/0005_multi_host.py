from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("monitor", "0004_dashboard_detail_fields"),
    ]

    operations = [
        migrations.AlterField(
            model_name="host",
            name="name",
            field=models.CharField(max_length=64, unique=True),
        ),
        migrations.AddField(
            model_name="host",
            name="reachable",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="host",
            name="last_error",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
    ]
