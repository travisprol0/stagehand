from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("monitor", "0002_host_disk_boot_net"),
    ]

    operations = [
        migrations.AddField(
            model_name="githubrunner",
            name="current_html_url",
            field=models.URLField(blank=True, max_length=512),
        ),
        migrations.AddField(
            model_name="githubrunner",
            name="current_job_name",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="githubrunner",
            name="current_repository",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="githubrunner",
            name="current_started_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="githubrunner",
            name="current_workflow_name",
            field=models.CharField(blank=True, max_length=255),
        ),
    ]
