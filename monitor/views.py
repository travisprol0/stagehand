from django.conf import settings
from django.http import HttpResponse
from django.shortcuts import render


def index(request):
    return render(
        request,
        "monitor/index.html",
        {"host_name": settings.HOST_NAME},
    )


def health(request):
    return HttpResponse("OK", content_type="text/plain")
