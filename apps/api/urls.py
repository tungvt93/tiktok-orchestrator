"""API URL configuration."""
from django.urls import path

from apps.api.views import health_check, webhook_video

urlpatterns = [
    path("health/", health_check, name="health-check"),
    path("upload_new_video", webhook_video, name="upload-new-video"),
]
