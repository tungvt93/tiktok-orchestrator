"""API serializers for TikTok Video Orchestrator."""
from rest_framework import serializers


class WebhookVideoSerializer(serializers.Serializer):
    """Serializer for the incoming video webhook payload."""

    channel_id = serializers.CharField(max_length=255)
    video_id = serializers.CharField(max_length=255)
    video_url = serializers.URLField(max_length=500, required=False)
    is_short = serializers.BooleanField(default=False)
