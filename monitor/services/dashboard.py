from django.conf import settings

from monitor.models import DockerContainer, GitHubRunner, Host


def get_current_host() -> Host | None:
    return Host.objects.filter(name=settings.HOST_NAME).first()


def get_host_containers(host: Host):
    return DockerContainer.objects.filter(host=host).exclude(status="removed")


def get_host_runners(host: Host):
    return GitHubRunner.objects.filter(host=host)
