"""Celery tasks for automatic/manual YouTube channel fetching and video rendering."""
import logging
import os
from celery import shared_task

from apps.core.models.youtube_channel import YouTubeChannel
from apps.core.models.video import Video
from apps.core.services.youtube_fetcher import fetch_recent_video_ids
from apps.core.services.downloader import download_video
from apps.core.services.renderer import render_video_with_outro
from apps.core.services.r2_storage import upload_clip
from apps.core.tasks.distribute import distribute_video

logger = logging.getLogger(__name__)


@shared_task
def fetch_and_process_channel_videos_manual(channel_id: str, max_videos: int, min_views: int):
    """
    Manual task to scan videos for a specific YouTube channel with max limit and view count filters.
    """
    try:
        channel = YouTubeChannel.objects.get(id=channel_id)
    except YouTubeChannel.DoesNotExist:
        logger.error("Channel with ID %s does not exist", channel_id)
        return

    logger.info(
        "Starting manual scan for channel: %s (Max: %d, Min views: %d)",
        channel.name, max_videos, min_views
    )

    # Tính toán dung lượng trống còn lại hôm nay của các profile cùng topic
    remaining_capacity = 0
    if channel.topic:
        profiles = channel.topic.tiktok_profiles.filter(is_active=True, vps__is_active=True)
        remaining_capacity = sum(max(0, p.daily_video_limit - p.videos_today) for p in profiles)
    
    # Giới hạn số video quét tối đa theo sức chứa còn lại thực tế
    if remaining_capacity <= 0:
        logger.info("Topic của kênh %s đã đạt giới hạn upload hôm nay (0 lượt trống). Bỏ qua quét.", channel.name)
        return
        
    actual_limit = min(max_videos, remaining_capacity)
    logger.info("Giới hạn quét thực tế sau khi tính toán sức chứa: %d video", actual_limit)

    # Tự động dựng URL chuẩn trỏ thẳng tới tab /videos của kênh để tránh gõ nhầm và lấy đúng danh sách video
    target_url = f"https://www.youtube.com/channel/{channel.channel_id}/videos"
    recent_videos = fetch_recent_video_ids(target_url, limit=actual_limit * 3)
    
    processed_count = 0
    for item in recent_videos:
        if processed_count >= actual_limit:
            break

        video_id = item["video_id"]
        video_url = item["url"]
        view_count = item["view_count"]

        # 1. Filter by minimum view count
        if view_count < min_views:
            logger.info("Skipping video %s: has %d views (requires %d)", video_id, view_count, min_views)
            continue

        # 2. Check if already exists in DB
        if Video.objects.filter(video_id=video_id).exists():
            continue

        # 3. Create video and queue rendering
        video = Video.objects.create(
            video_id=video_id,
            video_url=video_url,
            youtube_channel=channel,
            status=Video.Status.PENDING,
            is_split_original=False,
        )
        logger.info("Queued manual render for video %s (%d views)", video_id, view_count)
        render_and_distribute_video.delay(str(video.id))
        processed_count += 1


@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def render_and_distribute_video(self, video_id: str):
    """
    Pipeline task: Download, Render (speedup, zoom, outro), Upload to R2, and queue distribution.
    """
    try:
        video = Video.objects.get(id=video_id)
    except Video.DoesNotExist:
        logger.warning("Video %s deleted before rendering could start.", video_id)
        return

    # Update status to processing
    video.status = Video.Status.PROCESSING
    video.save(update_fields=["status"])

    downloaded_path = None
    rendered_path = None

    try:
        # Step 1: Download video from YouTube
        logger.info("Downloading source video for video_id %s...", video.video_id)
        downloaded_path, _ = download_video(video.video_url)

        # Step 2: Render video (Speed + Zoom + Outro)
        logger.info("Rendering video %s...", video.video_id)
        rendered_path = render_video_with_outro(downloaded_path, speed=1.05, zoom=1.05)

        # Step 3: Upload rendered video to Cloudflare R2
        logger.info("Uploading rendered video %s to Cloudflare R2...", video.video_id)
        r2_url = upload_clip(rendered_path)

        # Step 4: Update Video record with the R2 URL
        video.video_url = r2_url
        video.status = Video.Status.PENDING  # Reset status so distribute task doesn't skip it
        video.save(update_fields=["video_url", "status"])

        # Step 5: Enqueue final distribution
        logger.info("Queuing distribution task for video %s...", video.video_id)
        distribute_video.delay(str(video.id))

    except Exception as e:
        logger.exception("Render task failed for video %s: %s", video.video_id, e)
        video.status = Video.Status.FAILED
        video.error_log = f"Lỗi render: {str(e)}"
        video.save(update_fields=["status", "error_log"])

        # Retry after delay
        if self.request.retries < self.max_retries:
            raise self.retry(exc=e)
    finally:
        # Cleanup temporary local video files
        for path in [downloaded_path, rendered_path]:
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                    logger.debug("Cleaned up temp path: %s", path)
                except OSError:
                    pass
