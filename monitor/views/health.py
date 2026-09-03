from django.http import HttpResponse


def health(request):
    return HttpResponse("OK", content_type="text/plain")
