"""API views for TikTok Video Orchestrator."""
from django.conf import settings
from django.db import IntegrityError, connections

import redis
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from apps.api.serializers import WebhookVideoSerializer
from apps.core.models import YouTubeChannel, Video


@api_view(["POST"])
def webhook_video(request):
    """
    Receive new video notification from YouTube channel.

    POST /api/upload_new_video
    Body: {channel_id, video_id, is_short?, video_url?}

    Idempotent: duplicate video_id returns 200 without creating a new record.
    """
    serializer = WebhookVideoSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(
            {"status": "error", "errors": serializer.errors},
            status=status.HTTP_400_BAD_REQUEST,
        )

    data = serializer.validated_data
    channel_id = data["channel_id"]
    video_id = data["video_id"]
    
    # Auto-detect is_short by checking YouTube's URL redirect behavior
    # YouTube returns 200 for shorts and 303 redirect for long videos.
    try:
        import requests
        check_url = f"https://www.youtube.com/shorts/{video_id}"
        resp = requests.head(check_url, allow_redirects=False, timeout=5)
        is_short = (resp.status_code == 200)
    except Exception:
        # Fallback to payload if network fails
        is_short = data.get("is_short", False)

    # Get or create YouTubeChannel
    # Auto-assign the first available Topic (or default to None if no Topic exists)
    from apps.core.models.topic import Topic
    default_topic = Topic.objects.first()

    channel, _ = YouTubeChannel.objects.get_or_create(
        channel_id=channel_id,
        defaults={
            "name": channel_id,
            "channel_url": f"https://youtube.com/channel/{channel_id}",
            "topic": default_topic,
        },
    )

    # For non-short videos, check if there is an active TikTok profile corresponding to this channel's topic and is_beta=True
    if not is_short:
        from apps.core.models.tiktok_profile import TikTokProfile
        if not channel.topic or not TikTokProfile.objects.filter(topic=channel.topic, is_active=True, is_beta=True).exists():
            return Response(
                {
                    "status": "skipped",
                    "message": "No active beta TikTok profile found for channel topic, skipping processing",
                },
                status=status.HTTP_200_OK,
            )

    # Build video_url: use explicit URL if provided, otherwise construct from type
    video_url = data.get("video_url", "")
    if not video_url:
        if is_short:
            video_url = f"https://www.youtube.com/shorts/{video_id}"
        else:
            video_url = f"https://www.youtube.com/watch?v={video_id}"

    # Create Video (idempotent via UNIQUE constraint on video_id)
    try:
        video = Video.objects.create(
            video_id=video_id,
            video_url=video_url,
            youtube_channel=channel,
            status=Video.Status.PENDING,
            is_split_original=not is_short,
        )
    except IntegrityError:
        # Duplicate video_id — idempotent, return success
        return Response(
            {"status": "ok", "message": "Video already exists"},
            status=status.HTTP_200_OK,
        )

    # Enqueue appropriate task based on video type
    if is_short:
        from apps.core.tasks.distribute import distribute_video
        distribute_video.delay(str(video.id))
        task_name = "distribution"
    else:
        from apps.core.tasks.split import split_and_distribute_video
        split_and_distribute_video.delay(str(video.id))
        task_name = "splitting + distribution"

    return Response(
        {"status": "accepted", "message": f"Video queued for {task_name}"},
        status=status.HTTP_202_ACCEPTED,
    )


@api_view(["GET"])
def health_check(request):
    """
    Health check endpoint — verifies DB and Redis connectivity.

    GET /api/v1/health/
    """
    healthy = True
    checks = {}

    # Check database
    try:
        connections["default"].cursor()
        checks["database"] = "ok"
    except Exception as e:
        checks["database"] = f"error: {e}"
        healthy = False

    # Check Redis
    try:
        r = redis.Redis.from_url(settings.REDIS_URL)
        if r.ping():
            checks["redis"] = "ok"
        else:
            checks["redis"] = "error: no pong"
            healthy = False
    except Exception as e:
        checks["redis"] = f"error: {e}"
        healthy = False

    return Response(
        {"status": "healthy" if healthy else "unhealthy", "checks": checks},
        status=status.HTTP_200_OK if healthy else status.HTTP_503_SERVICE_UNAVAILABLE,
    )
