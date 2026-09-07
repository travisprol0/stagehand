from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("monitor", "0003_runner_current_job"),
    ]

    operations = [
        migrations.AddField(
            model_name="host",
            name="cpu_count",
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="dockercontainer",
            name="compose_project",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="dockercontainer",
            name="exit_code",
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="dockercontainer",
            name="ports",
            field=models.CharField(blank=True, max_length=512),
        ),
        migrations.AddField(
            model_name="dockercontainer",
            name="restart_count",
            field=models.IntegerField(default=0),
        ),
        migrations.AddField(
            model_name="dockercontainer",
            name="state_error",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="githubrunner",
            name="current_head_branch",
            field=models.CharField(blank=True, max_length=255),
        ),
    ]
